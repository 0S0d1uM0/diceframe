"""Application adapter for CoC combat: actor ownership, event batches and views."""
from __future__ import annotations
from copy import deepcopy
from uuid import uuid4

from src.engine.modules import ruleset_runtime
from src.engine.player_control import control_mode
from . import combat


def state(instance) -> dict | None:
    return ruleset_runtime.state(instance).get('combat')


def actor_record(sheet: dict, name: str, faction: str) -> dict:
    skills = {str(row.get('id') or ''): row.get('value') for row in sheet.get('skills', []) if isinstance(row, dict)}
    # Universal unarmed attack has a known CoC base skill; unknown NPC stats
    # are otherwise rejected by start_combat rather than invented by the UI.
    skills.setdefault('fighting_brawl', 25)
    attrs = sheet.get('attributes', {})
    if 'dex' in attrs:
        skills.setdefault('dodge', int(attrs['dex']) // 2)
    weapons = {'unarmed': {'damage_dice': '1d3', 'skill': 'fighting_brawl',
        'impale': False, 'uses_db': True, 'ammo': None}}
    for row in sheet.get('equipment', []):
        if isinstance(row, dict) and isinstance(row.get('coc_weapon'), dict):
            weapons[str(row['item_id'])] = deepcopy(row['coc_weapon'])
    return {'name': name, 'faction': faction, 'attributes': attrs,
            'hp': sheet.get('hp'), 'max_hp': sheet.get('max_hp'), 'skills': skills,
            'weapons': weapons, 'armor': sheet.get('armor_points', 0),
            'major_wound': bool(sheet.get('major_wound')), 'unconscious': bool(sheet.get('unconscious')),
            'dead': bool(sheet.get('deceased')), 'dying': bool(sheet.get('dying'))}


def start(instance, intent: dict) -> dict:
    if not intent.get('_requester_is_gm'):
        raise ValueError('Only the Keeper can start an encounter')
    if instance.action_queue:
        raise ValueError('Resolve already committed narrative actions before starting combat')
    old = state(instance)
    if old and old.get('status') == 'active':
        raise ValueError('An encounter is already active')
    npcs = intent.get('npc_ids')
    if not isinstance(npcs, list) or not npcs or len(npcs) > 12 or any(not isinstance(uid, str) or uid not in instance.npcs for uid in npcs):
        raise ValueError('Select 1–12 existing, fully statted NPCs')
    actors = {'player:' + uid: actor_record(instance.get_character_sheet(uid), row.get('character_name', uid), 'party')
              for uid, row in instance.players.items() if instance.is_alive(uid) and uid not in instance.away_players}
    for npc_id in npcs:
        npc = instance.npcs[npc_id]
        actors['npc:' + npc_id] = actor_record(npc, str(npc.get('name') or npc_id), str(npc.get('faction') or 'opposition'))
    return combat.start_combat(actors)


def actor_choices(instance, actor_id: str) -> list[dict]:
    encounter = state(instance)
    if not encounter or encounter['status'] != 'active':
        return []
    pending = encounter.get('pending_reaction')
    expected_actor = pending['target_id'] if pending else encounter['current']
    if actor_id != expected_actor:
        return []
    base = {'actor_id': actor_id, 'expected_revision': encounter['revision']}
    actor = encounter['actors'][actor_id]
    if pending:
        choices = [{**base, 'type': 'dodge'}]
        choices.extend({**base, 'type': 'fight_back', 'weapon_id': key}
            for key, weapon in actor['weapons'].items() if weapon.get('ammo') is None)
        return choices
    targets = [key for key, row in encounter['actors'].items()
               if row['faction'] != actor['faction'] and not row.get('dead') and not row.get('fled')]
    choices = [{**base, 'type': 'attack', 'target_id': target, 'weapon_id': key}
        for key, weapon in actor['weapons'].items() if weapon.get('ammo') is None or weapon['ammo'] > 0
        for target in targets]
    return [*choices, {**base, 'type': 'wait'}, {**base, 'type': 'flee'}]


def available(instance, uid: str, *, gm: bool = False) -> list[dict]:
    encounter = state(instance)
    if not encounter or encounter['status'] != 'active':
        return []
    actor_id = encounter.get('pending_reaction', {}).get('target_id') if encounter.get('pending_reaction') else encounter['current']
    if gm or actor_id == 'player:' + uid:
        return actor_choices(instance, actor_id)
    return []


def resolve(instance, intent: dict, rng) -> dict:
    try:
        ruleset_runtime.require_binding(instance, 'core:coc7e')
        kind = intent.get('type')
        current = state(instance)
        if kind == 'coc.combat.start':
            new = start(instance, intent)
            expected = current['revision'] if current else -1
            events = [{'type': 'combat.started', 'order': new['order']}]
        else:
            if not current:
                raise ValueError('No active encounter')
            actor_id = str(intent.get('actor_id') or '')
            requester = str(intent.get('submitted_by') or '')
            if not intent.get('_automatic') and not intent.get('_requester_is_gm'):
                if actor_id != 'player:' + requester or control_mode(instance, requester) != 'human':
                    raise ValueError('You may act only for your human-controlled investigator')
            permitted = {'type', 'actor_id', 'expected_revision', 'target_id', 'weapon_id', 'options'}
            raw = {key: value for key, value in intent.items() if key in permitted}
            new = combat.resolve_action(current, raw, rng)
            expected = current['revision']
            events = new.get('events', [])
        events = [{'type': 'intent.submitted', 'submitted_by': str(intent.get('submitted_by') or str(intent.get('actor_id') or '').removeprefix('player:'))}, *events]
        return {'ok': True, 'event_batch': {'batch_id': uuid4().hex, 'runtime_id': 'core:coc7e',
            'run_id': instance.run_id, 'expected_revision': expected, 'combat': new,
            'intent_type': str(kind or ''),
            'events': events, 'intent': {key: value for key, value in intent.items() if not key.startswith('_')}}}
    except (ValueError, TypeError, KeyError) as exc:
        return {'ok': False, 'code': 'COC_INTENT_REJECTED', 'error': str(exc)}


def apply(instance, batch: dict) -> dict:
    ruleset_runtime.require_binding(instance, 'core:coc7e')
    if batch.get('runtime_id') != 'core:coc7e' or batch.get('run_id') != instance.run_id:
        raise ValueError('Event batch belongs to another runtime or run')
    ledger = ruleset_runtime.event_ledger(instance)
    if any(row.get('batch_id') == batch.get('batch_id') for row in ledger):
        return {'applied': False, 'already_applied': True}
    old = state(instance)
    if batch.get('expected_revision') != (old['revision'] if old else -1):
        raise ValueError('Combat changed before applying event batch')
    encounter = deepcopy(batch['combat'])
    ruleset_runtime.state(instance)['combat'] = encounter
    ledger.append({key: deepcopy(batch[key]) for key in ('batch_id', 'runtime_id', 'run_id', 'events', 'intent')})
    for actor_id, actor in encounter['actors'].items():
        if actor_id.startswith('player:'):
            sheet = instance.get_character_sheet(actor_id.removeprefix('player:'))
        else:
            sheet = instance.npcs[actor_id.removeprefix('npc:')]
        sheet.update(hp=actor['hp'], major_wound=bool(actor.get('major_wound')),
            unconscious=bool(actor.get('unconscious')), dying=bool(actor.get('dying')),
            deceased=bool(actor.get('dead')))
        sheet['status'] = 'dead' if actor.get('dead') else 'downed' if actor.get('unconscious') else 'normal'
        for row in sheet.get('equipment', []):
            if isinstance(row, dict) and isinstance(row.get('coc_weapon'), dict):
                saved = actor['weapons'].get(str(row.get('item_id')))
                if saved is not None:
                    row['coc_weapon']['ammo'] = saved['ammo']
    return {'applied': True, 'batch_id': batch['batch_id'], 'events': deepcopy(batch['events'])}


def automatic(instance) -> dict | None:
    encounter = state(instance)
    if not encounter or encounter['status'] != 'active':
        return None
    actor_id = encounter['pending_reaction']['target_id'] if encounter.get('pending_reaction') else encounter['current']
    if actor_id.startswith('player:') and control_mode(instance, actor_id.removeprefix('player:')) != 'ai':
        return None
    choices = actor_choices(instance, actor_id)
    if not choices:
        return None
    # NPCs have a transparent baseline policy; hosted investigators may replace
    # this with a validated model choice through HostedIntentChoiceRuntime.
    return {**choices[0], '_automatic': True}


def view(instance, uid: str = '', gm: bool = False) -> dict:
    encounter = state(instance)
    result = {'status': 'none' if not encounter else encounter['status'],
              'limitations': ['暂不支持连发／自动火力、战技、濒死轮末结算和战斗内急救']}
    if not encounter:
        return result
    result.update(revision=encounter['revision'], round=encounter['round'], current=encounter['current'],
                  order=deepcopy(encounter['order']), pending_reaction=deepcopy(encounter.get('pending_reaction')),
                  actors=[{'actor_id': aid, 'name': row['name'], 'faction': row['faction'],
                           'dead': row.get('dead', False), 'unconscious': row.get('unconscious', False),
                           **({'hp': row['hp'], 'max_hp': row['max_hp']} if gm or aid == 'player:' + uid else {})}
                          for aid, row in encounter['actors'].items()])
    if not gm and result.get('pending_reaction'):
        result['pending_reaction'].pop('attack_skill', None)
    return result
