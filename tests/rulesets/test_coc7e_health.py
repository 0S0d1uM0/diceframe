from types import SimpleNamespace
from src.commands.madness_tracker import MadnessTracker
from src.commands.player_state_applier import PlayerStateApplier
from src.engine.game_instance import GameInstance
from src.rulesets.coc7e.runtime import Coc7eRuntime


def fixture():
    inst = GameInstance(game_key=('web', 'injury', 'bot'))
    inst.put_player('p', {'user_id': 'p', 'character_name': '调查员',
        'character_sheet': {'hp': 10, 'max_hp': 10, 'attributes': {'con': 50}}})
    return inst, PlayerStateApplier(MadnessTracker())


def apply(inst, applier, update):
    applier.apply_players(inst, {'p': update}, vitality_runtime=Coc7eRuntime())


def test_accumulated_minor_injuries_cause_unconsciousness_without_legacy_instant_death():
    inst, applier = fixture()
    for damage in (3, 3, 4): apply(inst, applier, {'hp_change': -damage})
    sheet = inst.get_character_sheet('p')
    assert sheet['hp'] == 0 and sheet['unconscious'] and not sheet.get('deceased')
    assert not sheet['major_wound'] and not sheet['dying']
    apply(inst, applier, {'status': 'normal', 'hp_change': 5, 'stat_changes': {'hp': 10}})
    assert sheet['hp'] == 0 and sheet['status'] == 'downed' and not sheet.get('deceased')


def test_major_wound_uses_raw_single_injury_and_authoritative_con(monkeypatch):
    inst, applier = fixture()
    monkeypatch.setattr('src.rulesets.coc7e.health.dice_rng.roll', lambda _: SimpleNamespace(total=80))
    apply(inst, applier, {'hp_change': -5})
    sheet = inst.get_character_sheet('p')
    assert sheet['hp'] == 5 and sheet['major_wound'] and sheet['unconscious']
    assert sheet['coc_last_injury_check']['roll'] == 80
    apply(inst, applier, {'hp_change': -10})
    assert sheet['deceased'] and sheet['hp'] == 0


def test_domain_madness_is_not_removed_by_legacy_round_timer():
    inst, _ = fixture()
    sheet = inst.get_character_sheet('p')
    sheet['madness'] = {'type': 'temporary', 'duration_hours': 8, 'bout_rounds': 3}
    MadnessTracker().tick_madness(inst)
    assert sheet['madness']['type'] == 'temporary'
