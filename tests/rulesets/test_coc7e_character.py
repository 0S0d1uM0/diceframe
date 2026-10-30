from copy import deepcopy
from types import SimpleNamespace
import pytest
from src.rulesets.coc7e import character
from src.rulesets.coc7e.runtime import Coc7eRuntime
from src.rulesets.coc7e.mechanics import opposed_result, success_rank, wound_result, sanity_transition
from src.rulesets.builtin import build_default_ruleset_registry


def test_same_form_derives_hp_san_mp_db_and_skill_points():
    draft = character.example_draft()
    assert not character.validate(draft)
    sheet = character.finalize(SimpleNamespace(rule_id='coc7e'), draft)
    assert sheet['hp'] == 10 and sheet['sanity'] == 60 and sheet['magic_points'] == 12
    assert sheet['damage_bonus'] == '0'
    assert next(row['value'] for row in sheet['skills'] if row['id'] == 'spot_hidden') == 60
    assert next(row['value'] for row in sheet['skills'] if row['id'] == 'own_language') == 80


@pytest.mark.parametrize('field,value', [('age', 40), ('age', True), ('luck', 51), ('occupation', 'invented')])
def test_invalid_draft_is_rejected_without_clamping(field, value):
    draft = character.example_draft(); draft[field] = value
    before = deepcopy(draft)
    assert character.validate(draft)
    assert draft == before
    with pytest.raises(ValueError): character.finalize(SimpleNamespace(rule_id='coc7e'), draft)


def test_cannot_buy_mythos_or_exceed_occupation_and_interest_budgets():
    draft = character.example_draft()
    draft['interest_spends']['cthulhu_mythos'] = 1
    assert character.validate(draft)
    draft = character.example_draft(); draft['occupation_spends']['spot_hidden'] = 99
    assert character.validate(draft)


def test_submission_rebuilds_forged_resource_and_skill_fields_from_canonical_draft():
    rule = SimpleNamespace(rule_id='coc7e')
    runtime = Coc7eRuntime()
    sheet = runtime.finalize_character(rule, character.example_draft())
    sheet['hp'] = 9000; sheet['skills'][0]['value'] = 999
    rebuilt = runtime.normalize_character_submission(rule, sheet)
    assert rebuilt['hp'] == 10 and rebuilt['skills'][0]['value'] == 60
    sheet['ruleset_character']['rule_binding']['rule_id'] = 'freeform_coc'
    with pytest.raises(ValueError): runtime.normalize_character_submission(rule, sheet)


def test_new_runtime_is_explicit_and_old_rule_stays_legacy():
    registry = build_default_ruleset_registry()
    assert registry.resolve({}).runtime_id == 'core:legacy'
    assert registry.resolve({'runtime': 'core:coc7e'}).runtime_id == 'core:coc7e'


def test_combat_opposed_ties_have_distinct_dodge_and_fight_back_rules():
    assert opposed_result(40, 60, 40, 60, mode='dodge') == 'defender'
    assert opposed_result(40, 60, 40, 60, mode='fight_back') == 'attacker'
    assert opposed_result(90, 60, 90, 60, mode='fight_back') == 'tie'
    assert opposed_result(40, 70, 40, 60) == 'attacker'
    assert success_rank(5, 50) == 3 and success_rank(1, 0) == 4


def test_wounds_use_one_blow_and_maximum_hp_not_current_hp_or_size():
    assert wound_result(11, 11, 5)['major_wound'] is False
    assert wound_result(11, 11, 6)['con_check_required'] is True
    assert wound_result(12, 3, 3)['dying'] is False
    assert wound_result(12, 3, 3, major_wound=True)['dying'] is True
    assert wound_result(12, 12, 12)['dead'] is True


def test_sanity_single_shock_int_gate_daily_loss_and_permanent_are_distinct():
    assert sanity_transition(60, 5, 60, 0)['needs_int_check']
    assert sanity_transition(60, 5, 60, 0, int_roll=40)['temporary']
    assert not sanity_transition(60, 5, 60, 0, int_roll=80)['temporary']
    assert sanity_transition(50, 2, 60, 10)['indefinite']
    assert sanity_transition(2, 3, 60, 10)['permanent']
