from copy import deepcopy
from types import SimpleNamespace
import random
import pytest
from src.engine.game_instance import GameInstance, GameState
from src.engine.modules import ruleset_runtime
from src.rulesets.coc7e.runtime import Coc7eRuntime
from src.rulesets.coc7e.character import example_draft
from src.rulesets.automation import advance_automatic_intents


def fixture():
    runtime = Coc7eRuntime(); rule = SimpleNamespace(rule_id='coc7e')
    inst = GameInstance(game_key=('web', 'combat-runtime', 'bot'), rule_id='coc7e')
    inst.state = GameState.ACTIVE_ACTION; inst.gm_uid = 'p'
    assert inst.bind_ruleset_runtime(runtime.game_binding(rule, 'zh-CN'))
    sheet = runtime.finalize_character(rule, example_draft())
    assert inst.ruleset_binding_matches(sheet['ruleset_character']['rule_binding'])
    inst.put_player('p', {'user_id': 'p', 'character_name': '调查员', 'character_sheet': sheet})
    inst.npcs['n'] = {'name': '敌人', 'hp': 10, 'max_hp': 10,
        'attributes': {'str': 50, 'siz': 50, 'dex': 30, 'con': 50},
        'skills': [{'id': 'fighting_brawl', 'value': 25}, {'id': 'dodge', 'value': 15}]}
    return runtime, inst


def test_character_binding_matches_actual_new_game_and_combat_batch_is_replay_safe():
    runtime, inst = fixture()
    intent = runtime.prepare_intent_submission({'type': 'coc.combat.start', 'npc_ids': ['n'], 'expected_run_id': inst.run_id}, 'p', True)
    resolved = runtime.resolve_intent(inst, intent, random.Random(1))
    assert resolved['ok']
    batch = resolved['event_batch']
    assert runtime.apply_event_batch(inst, batch)['applied']
    before = deepcopy(inst.to_dict())
    assert runtime.apply_event_batch(inst, batch)['already_applied']
    assert inst.to_dict() == before
    restored = GameInstance.from_dict(inst.to_dict())
    assert ruleset_runtime.state(restored)['combat']['status'] == 'active'
    assert restored.ruleset_binding_matches(runtime.game_binding(SimpleNamespace(rule_id='coc7e'), 'zh-CN'))


def test_human_cannot_forge_automatic_privilege_or_modify_other_actor():
    runtime, inst = fixture()
    with pytest.raises(ValueError):
        runtime.prepare_intent_submission({'type': 'wait', '_automatic': True}, 'p', False)
    intent = runtime.prepare_intent_submission({'type': 'coc.combat.start', 'npc_ids': ['n'], 'expected_run_id': inst.run_id}, 'p', False)
    assert not runtime.resolve_intent(inst, intent, random.Random(1))['ok']


def test_unknown_npc_attributes_fail_closed_without_creating_combat():
    runtime, inst = fixture(); inst.npcs['n'].pop('attributes')
    intent = runtime.prepare_intent_submission({'type': 'coc.combat.start', 'npc_ids': ['n'], 'expected_run_id': inst.run_id}, 'p', True)
    assert not runtime.resolve_intent(inst, intent, random.Random(1))['ok']
    assert 'combat' not in ruleset_runtime.state(inst)


def test_combat_view_does_not_expose_enemy_hp_or_skill_internals_to_investigator():
    runtime, inst = fixture()
    intent = runtime.prepare_intent_submission({'type': 'coc.combat.start', 'npc_ids': ['n'], 'expected_run_id': inst.run_id}, 'p', True)
    runtime.apply_event_batch(inst, runtime.resolve_intent(inst, intent, random.Random(1))['event_batch'])
    view = runtime.gameplay_view(inst, 'p', False)
    enemy = next(row for row in view['combat']['actors'] if row['actor_id'] == 'npc:n')
    assert 'hp' not in enemy and 'skills' not in enemy and 'weapons' not in enemy


def test_ai_luck_decision_reserves_resources_and_never_chooses_for_human():
    from src.engine.player_control import set_control
    runtime, inst = fixture(); rule = SimpleNamespace()
    assert runtime.automatic_luck_decision(inst, rule, {'actor_uid': 'p', 'luck_cost': 5}) is None
    set_control(inst, 'p', 'ai')
    assert runtime.automatic_luck_decision(inst, rule, {'actor_uid': 'p', 'luck_cost': 5}) is True
    assert runtime.automatic_luck_decision(inst, rule, {'actor_uid': 'p', 'luck_cost': 20}) is False


def test_keeper_view_retains_percentile_resources_without_d20_modifiers():
    runtime, inst = fixture()
    view = runtime.build_llm_view(inst)
    sheet = view['players']['p']['character_sheet']
    assert '_modifiers' not in sheet and isinstance(sheet['skills'], dict)
    assert sheet['magic_points'] == inst.get_character_sheet('p')['magic_points']
    assert list(view)[0] == 'coc_keeper_contract'
    assert isinstance(inst.get_character_sheet('p')['skills'], list)


def test_campaign_modes_are_gm_only_and_cannot_rewrite_an_existing_run():
    runtime, inst = fixture()
    raw = {'type': 'coc.campaign.configure', 'mode': 'endless', 'premise': '海港调查',
           'expected_revision': 0, 'expected_run_id': inst.run_id}
    denied = runtime.resolve_intent(inst, runtime.prepare_intent_submission(raw, 'p', False), random.Random(1))
    assert not denied['ok']
    result = runtime.resolve_intent(inst, runtime.prepare_intent_submission(raw, 'p', True), random.Random(1))
    assert result['ok'] and runtime.apply_event_batch(inst, result['event_batch'])['applied']
    assert runtime.build_llm_view(inst)['original_campaign']['mode'] == 'endless'
    assert runtime.gameplay_view(inst, 'p', False)['campaign'] == {}
    inst.append_log_entry({'round': 1, 'actions': [{'user_id': 'p', 'text': '我调查'}], 'gm_response': '结果'})
    result = runtime.resolve_intent(inst, runtime.prepare_intent_submission({**raw, 'mode': 'regular', 'expected_revision': 1}, 'p', True), random.Random(1))
    assert not result['ok']


@pytest.mark.parametrize('strength', [15, 20, 50])
def test_percentile_attributes_do_not_take_legacy_times_five_path(strength):
    import json
    from pathlib import Path
    from src.engine.checks import resolve_check_request
    from src.rules.rule_system import RuleSystem
    runtime, inst = fixture()
    sheet = inst.get_character_sheet('p'); sheet['attributes']['str'] = strength
    template = json.loads(Path('templates/rules/coc7e.json').read_text(encoding='utf-8'))
    rule = RuleSystem(template)
    action = {'user_id': 'p', 'text': '我抬起木箱', 'dice_value': 21, 'dice_rolls': [21],
              'check_request': {'dice_system': 'd100', 'actor_uid': 'p', 'attribute': 'str'}}
    result = resolve_check_request(inst, action, rule)
    assert result['threshold'] == strength
