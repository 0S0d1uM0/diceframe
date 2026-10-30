from types import SimpleNamespace
import pytest
from src.engine.game_instance import GameInstance, GameState
from src.engine.modules import progression_state
from src.rulesets.coc7e.sanity import apply_event


def fixture():
    inst = GameInstance(game_key=('web', 'sanity', 'bot'))
    inst.state = GameState.ACTIVE_ACTION
    inst.put_player('p', {'user_id': 'p', 'character_name': 'Investigator',
        'character_sheet': {'hp': 10, 'max_hp': 10, 'sanity': 60, 'attributes': {'int': 50}}})
    return inst


def dice(monkeypatch, rolls):
    stream = iter(rolls)
    monkeypatch.setattr('src.rulesets.coc7e.sanity.dice_rng.roll', lambda _: SimpleNamespace(total=next(stream)))


def test_success_uses_success_formula_not_half_failed_loss(monkeypatch):
    inst = fixture(); dice(monkeypatch, [40])
    apply_event(inst, 'p', {'san_check_loss': '0/1d6'})
    assert inst.get_character_sheet('p')['sanity'] == 60


def test_failed_shock_records_int_roll_and_duration_only_after_int_success(monkeypatch):
    inst = fixture(); dice(monkeypatch, [70, 5, 40, 8, 3])
    apply_event(inst, 'p', {'san_check_loss': '0/1d6'})
    sheet = inst.get_character_sheet('p')
    assert sheet['sanity'] == 55 and sheet['madness']['duration_hours'] == 8
    assert sheet['madness']['bout_rounds'] == 3
    assert sheet['coc_sanity']['last_check']['int_roll'] == 40


def test_same_event_is_idempotent_without_second_rng_or_loss(monkeypatch):
    inst = fixture(); dice(monkeypatch, [70, 2])
    apply_event(inst, 'p', {'san_check_loss': '0/1d6'})
    apply_event(inst, 'p', {'san_check_loss': '0/1d6'})
    assert inst.get_character_sheet('p')['sanity'] == 58


@pytest.mark.parametrize('formula', ['1d6', '0/-1d6', '0/100000d6', '0/1d6/1d10', 'eval(1)/1d6'])
def test_invalid_san_event_does_not_roll_or_mutate(monkeypatch, formula):
    inst = fixture()
    monkeypatch.setattr('src.rulesets.coc7e.sanity.dice_rng.roll', lambda _: pytest.fail('No RNG on invalid event'))
    with pytest.raises(ValueError): apply_event(inst, 'p', {'san_check_loss': formula})
    assert inst.get_character_sheet('p')['sanity'] == 60


def test_daily_loss_is_reset_only_by_authoritative_world_day(monkeypatch):
    inst = fixture(); dice(monkeypatch, [70, 3, 70, 2])
    apply_event(inst, 'p', {'san_check_loss': '0/1d6'})
    inst.round_number += 1
    inst.world_state['clock']['day'] = 2
    apply_event(inst, 'p', {'san_check_loss': '0/1d6'})
    sheet = inst.get_character_sheet('p')
    assert sheet['coc_sanity']['daily_start_san'] == 57
    assert sheet['coc_sanity']['daily_loss'] == 2
