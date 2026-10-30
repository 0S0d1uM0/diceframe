"""Authorized party planning with atomic saves and optimistic model admission."""
from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import logging
from typing import Any, Awaitable, Callable

from src.engine import party_planning as planning
from src.engine import module_hooks
from src.engine.game_state import GameState
from src.engine.participant_view import Viewer
from src.engine.player_control import control_mode
from src.engine.modules import session_stats, ai_seats
from src.engine.staged_transaction import StagedGameTransaction


@dataclass(frozen=True)
class PlanningDependencies:
    get_instance: Callable[[str], Any]
    save_instance: Callable[[Any], Awaitable[None]]
    load_rule: Callable[[Any], Any]
    deliberate: Callable[[Any], Awaitable[list[dict]]] | None = None


def _discussion_scope(instance: Any) -> dict:
    """Fence authority and knowledge, excluding derived counters/media caches.

    Publication copies only the plan and model accounting into a fresh stage;
    concurrently refreshed summaries or delivery receipts are never overwritten.
    """
    data = deepcopy(instance.to_dict())
    modules = data.get('modules', {})
    notes = deepcopy(modules.get('narrative_notes', {}))
    notes.pop('summary', None)
    seats = deepcopy(modules.get('ai_seats', {})); seats.pop('outcomes', None)
    return {'run_id': instance.run_id, 'state': instance.state.value, 'rule_id': instance.rule_id,
        'gm_uid': instance.gm_uid, 'players': deepcopy(instance.players),
        'npcs': deepcopy(instance.npcs), 'actions': deepcopy(instance.action_queue),
        'pending_actions': deepcopy(instance.pending_actions), 'ready': sorted(instance.ready_players),
        'away': sorted(instance.away_players), 'world': deepcopy(instance.world_state),
        'log': deepcopy(instance.log), 'notes': notes, 'ai_policy': seats,
        'channels': modules.get('private_channels'), 'rules': modules.get('ruleset_runtime'),
        'lifecycle': modules.get('run_finale'), 'room': modules.get('room_access'),
        'directives': modules.get('round_presentation', {}).get('gm_directives')}


class PartyPlanningService:
    def __init__(self, deps: PlanningDependencies):
        self.deps = deps

    def read(self, key: str, viewer: Viewer) -> dict:
        inst = self.deps.get_instance(key)
        if inst is None:
            return {'ok': False, 'code': 'GAME_NOT_FOUND'}
        if not viewer.is_member:
            return {'ok': False, 'code': 'FORBIDDEN'}
        rule = self.deps.load_rule(inst)
        enabled = bool(rule and rule.template.get('party_planning'))
        return {'ok': True, 'enabled': enabled, 'plan': planning.view(inst),
                'is_gm': viewer.is_gm, 'viewer_uid': viewer.uid,
                'names': {uid: row.get('character_name', uid) for uid, row in inst.players.items()}}

    async def update(self, key: str, viewer: Viewer, operation: str, body: Any) -> dict:
        if not isinstance(body, dict):
            return {'ok': False, 'code': 'INVALID_REQUEST'}
        inst = self.deps.get_instance(key)
        if inst is None:
            return {'ok': False, 'code': 'GAME_NOT_FOUND'}
        if not viewer.is_member or (operation in ('generate', 'commit') and not viewer.is_gm):
            return {'ok': False, 'code': 'FORBIDDEN'}
        uid = viewer.uid
        if operation not in ('generate', 'commit') and (uid not in inst.players or control_mode(inst, uid) != 'human'):
            return {'ok': False, 'code': 'FORBIDDEN'}
        try:
            async with inst.authoritative_write() as entered:
                if not entered:
                    raise ValueError('Game busy')
                async with inst._lock:
                    if self.deps.get_instance(key) is not inst or not inst.run_writable():
                        raise ValueError('Game changed or is read-only')
                    rule = self.deps.load_rule(inst)
                    if not rule or not rule.template.get('party_planning'):
                        raise ValueError('This rule does not enable party planning')
                    if inst.state not in {GameState.ACTIVE_ACTION, GameState.PAUSED} or inst.round_processing_in_flight():
                        raise ValueError('Planning requires an idle action phase')
                    if module_hooks.combat_view(inst)['combat_active']:
                        raise ValueError('Resolve the current combat turn before narrative planning')
                    plan = planning.view(inst)
                    if (body.get('run_id') != plan['run_id'] or type(body.get('round')) is not int
                            or body['round'] != plan['round'] or type(body.get('expected_revision')) is not int
                            or body['expected_revision'] != plan['revision']):
                        raise ValueError('Stale plan; refresh')
                    transaction = StagedGameTransaction(inst)
                    expected_context = _discussion_scope(inst)
                staged = transaction.staged
                if operation == 'generate':
                    if self.deps.deliberate is None or plan['committed']:
                        raise ValueError('AI discussion unavailable')
                    proposals = await self.deps.deliberate(staged)
                    if not proposals:
                        raise ValueError('No AI proposals generated')
                    for row in proposals:
                        actor = row['uid']
                        if actor not in plan['roster'] or control_mode(staged, actor) != 'ai':
                            raise ValueError('Invalid AI investigator')
                        current = planning.view(staged)
                        planning.change(staged, 'propose', actor, {**current,
                            **row, 'expected_revision': current['revision']})
                    current = planning.view(staged)
                    # A second review pass explicitly accepts the resulting plan.
                    for row in proposals:
                        if row.get('confirmed') is True:
                            current = planning.change(staged, 'confirm', row['uid'],
                                {**current, 'expected_revision': current['revision']})
                    current['reviews'] = {row['uid']: {'confirmed': row.get('confirmed') is True,
                        'reason': str(row.get('review_reason') or '')[:1000]} for row in proposals}
                    planning.store(staged, current)
                elif operation == 'commit':
                    if staged.state == GameState.PAUSED:
                        await staged.resume()
                    planning.commit(staged, body)
                else:
                    planning.change(staged, operation, uid, body)
                async with inst._lock:
                    if self.deps.get_instance(key) is not inst:
                        raise ValueError('Game replaced during planning')
                    if operation == 'generate':
                        current_context = _discussion_scope(inst)
                        if current_context != expected_context:
                            logging.getLogger(__name__).warning(
                                'Party discussion invalidated by changed scope fields: %s',
                                ', '.join(key for key in expected_context
                                          if current_context.get(key) != expected_context[key]))
                            raise ValueError('Investigator knowledge or party decisions changed during discussion')
                        # Merge only this command's owned effects; retain live
                        # background summaries, counters and delivery receipts.
                        refreshed = StagedGameTransaction(inst)
                        planning.store(refreshed.staged, planning.view(staged))
                        session_stats.record_llm_usage(refreshed.staged,
                            session_stats.total_tokens(staged) - session_stats.total_tokens(transaction.before),
                            calls=session_stats.total_llm_calls(staged) - session_stats.total_llm_calls(transaction.before))
                        outcomes = ai_seats.settings_state(staged)['outcomes']
                        for row in proposals:
                            if row['uid'] in outcomes:
                                ai_seats.record_outcome(refreshed.staged, row['uid'], outcomes[row['uid']])
                        transaction = refreshed
                    transaction.publish(inst)
                    try:
                        await self.deps.save_instance(inst)
                    except BaseException:
                        transaction.rollback(inst)
                        raise
            return self.read(key, viewer)
        except ValueError as exc:
            return {'ok': False, 'code': 'PLAN_REJECTED', 'error': str(exc)}
        except Exception:
            return {'ok': False, 'code': 'PLAN_FAILED', 'error': 'Planning failed; no plan was committed'}

