"""Persisted, revisioned party deliberation. Proposals never resolve actions.

The private-channels owner retains this optional public discussion payload.
Only the application service authorizes and atomically commits a ready plan.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any

from src.engine.modules import private_channels, progression_state
from src.engine.player_control import get_control
from src.engine.character_utils import is_conscious


def roster(instance: Any) -> dict:
    return {uid: get_control(instance, uid) for uid in instance.players
            if instance.is_alive(uid) and is_conscious(instance.get_character_sheet(uid))
            and uid not in instance.away_players}


def view(instance: Any) -> dict:
    plan = private_channels.party_plan(instance)
    scope = {'run_id': instance.run_id, 'round': progression_state.round_value(instance),
             'roster': roster(instance)}
    if not isinstance(plan, dict) or any(plan.get(key) != value for key, value in scope.items()):
        return {**scope, 'schema_version': 1, 'revision': 0, 'messages': [],
                'proposals': {}, 'confirmed': [], 'committed': False}
    if plan.get('schema_version') != 1:
        raise ValueError('Unsupported party plan version')
    return deepcopy(plan)


def store(instance: Any, plan: dict) -> None:
    private_channels.replace_party_plan(instance, plan)


def ready(plan: dict) -> bool:
    members = set(plan['roster'])
    return bool(members) and members == set(plan['proposals']) and members <= set(plan['confirmed'])


def change(instance: Any, operation: str, uid: str, body: dict) -> dict:
    plan = view(instance)
    if (body.get('run_id') != plan['run_id'] or type(body.get('round')) is not int
            or body['round'] != plan['round'] or type(body.get('expected_revision')) is not int
            or body['expected_revision'] != plan['revision']):
        raise ValueError('Plan changed; refresh before confirming')
    if plan['committed']:
        raise ValueError('Plan already submitted to Keeper')
    if uid not in plan['roster']:
        raise ValueError('Active investigator required')
    if operation in ('message', 'propose'):
        text = body.get('text')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise ValueError('Text must contain 1–2000 characters')
        text = text.strip()
        if operation == 'message':
            plan['messages'] = [*plan['messages'], {'uid': uid, 'text': text}][-60:]
        else:
            fields = {key: body.get(key, '') for key in ('selected_skill', 'selected_attribute', 'target_text')}
            if any(not isinstance(value, str) or len(value) > 200 for value in fields.values()):
                raise ValueError('Invalid action selection')
            plan['proposals'][uid] = {'text': text, **fields}
        # Any new discussion can change consent, including a question or objection.
        plan['confirmed'] = []
        plan.pop('reviews', None)
    elif operation == 'confirm':
        if uid not in plan['proposals']:
            raise ValueError('Propose your action before confirming')
        if uid not in plan['confirmed']:
            plan['confirmed'].append(uid)
    else:
        raise ValueError('Unknown planning operation')
    plan['revision'] += 1
    store(instance, plan)
    return plan


def commit(instance: Any, body: dict) -> dict:
    """Called only on an isolated aggregate after application authorization."""
    plan = view(instance)
    if (body.get('run_id') != plan['run_id'] or body.get('round') != plan['round']
            or type(body.get('expected_revision')) is not int or body['expected_revision'] != plan['revision']):
        raise ValueError('Plan changed; refresh before submitting')
    if plan['committed']:
        return plan
    if not ready(plan) or instance.action_queue or not instance.can_accept_actions():
        raise ValueError('Every investigator must confirm the current plan before submission')
    for uid, proposal in plan['proposals'].items():
        added = instance._add_action_locked(uid, proposal['text'],
            selected_skill=proposal['selected_skill'], selected_attribute=proposal['selected_attribute'],
            target_text=proposal['target_text'], source='party_plan',
            action_metadata={'source': 'party_plan', 'plan_revision': plan['revision']},
            defer_out_of_phase=False)
        if not added:
            raise ValueError('An investigator cannot act')
    plan['committed'] = True
    plan['revision'] += 1
    store(instance, plan)
    return plan
