"""Independent behavior oracles for the supported combat subset.

Replaces the unaccepted generated draft: that draft supplied impossible RNG
faces, used max_hp=0 for unconscious characters and expected extra turns after
reactions. Coverage below checks rule outcomes and validates every RNG face.
"""
from copy import deepcopy
import random
import pytest
from src.rulesets.coc7e.combat import start_combat, resolve_action


class Rng:
    def __init__(self, values=()): self.values = list(values); self.calls = []
    def randint(self, low, high):
        assert self.values, f'Unexpected dice roll {low}..{high}'
        value = self.values.pop(0)
        assert low <= value <= high, f'Impossible dice face {value} for {low}..{high}'
        self.calls.append((low, high, value))
        return value


def actor(dex=50, faction='enemy', *, hp=20, maximum=20, armor=0, strength=50, size=50):
    return {'name': faction, 'faction': faction, 'hp': hp, 'max_hp': maximum, 'armor': armor,
        'attributes': {'str': strength, 'siz': size, 'dex': dex, 'con': 50},
        'skills': {'fighting_brawl': 60, 'dodge': 40, 'firearms_handgun': 60},
        'weapons': {'club': {'damage_dice': '1d6', 'skill': 'fighting_brawl', 'impale': False, 'uses_db': True, 'ammo': None},
                    'pistol': {'damage_dice': '1d10', 'skill': 'firearms_handgun', 'impale': True, 'uses_db': False, 'ammo': 3}}}


def fixture(**defender):
    return start_combat({'player:a': actor(70, 'party'), 'npc:b': actor(**defender)})


def perform(state, aid, kind, rng=(), **kwargs):
    before = deepcopy(state)
    result = resolve_action(state, {'expected_revision': state['revision'], 'actor_id': aid, 'type': kind, **kwargs}, Rng(rng))
    assert state == before
    return result


def attack(state, roll=40, weapon='club', extra=()):
    return perform(state, 'player:a', 'attack', [roll, *extra], target_id='npc:b', weapon_id=weapon)


def damage(events): return next(row for row in events if row['type'] == 'combat.damage')


def test_dex_order_tie_and_immutable_start():
    actors = {'npc:z': actor(70), 'player:a': actor(70, 'party'), 'npc:c': actor(40)}
    before = deepcopy(actors); state = start_combat(actors)
    assert actors == before and state['order'] == ['npc:z', 'player:a', 'npc:c']
    assert state['current'] == 'npc:z'


@pytest.mark.parametrize('major,dying', [(False, False), (True, True)])
def test_zero_hp_is_unconscious_and_only_major_wound_is_dying(major, dying):
    row = actor(hp=0); row['major_wound'] = major
    state = start_combat({'player:a': actor(70, 'party'), 'npc:b': row})
    target = state['actors']['npc:b']
    assert target['unconscious'] and target['dying'] is dying and not target['dead']
    assert 'npc:b' not in state['order']


def test_melee_attack_records_real_roll_and_waits_for_reaction():
    state = attack(fixture())
    assert state['pending_reaction']['attack_skill'] == 60
    assert state['actors']['npc:b']['hp'] == 20
    assert state['current'] == 'npc:b'
    assert any(row['type'] == 'combat.attack' and row['roll'] == 40 for row in state['events'])


def test_dodge_equal_success_level_defends_without_damage():
    state = attack(fixture())
    result = perform(state, 'npc:b', 'dodge', [30])
    assert result['actors']['npc:b']['hp'] == 20
    assert result['current'] == 'npc:b'  # Its ordinary DEX turn still occurs.
    assert result['round'] == 1


def test_fight_back_equal_success_level_favors_initiator():
    result = perform(attack(fixture()), 'npc:b', 'fight_back', [40, 2], weapon_id='club')
    assert result['actors']['npc:b']['hp'] == 18
    assert result['actors']['player:a']['hp'] == 20


def test_failed_attacker_can_receive_counterattack_and_no_extreme_counter_damage():
    state = attack(fixture(), 90)
    result = perform(state, 'npc:b', 'fight_back', [1, 2], weapon_id='club')
    assert result['actors']['player:a']['hp'] == 18
    assert damage(result['events'])['damage'] == 2
    assert any(row.get('mode') == 'counter_attack_normal' for row in result['events'])


def test_reaction_does_not_skip_an_intervening_normal_turn():
    state = start_combat({'player:a': actor(80, 'party'), 'player:c': actor(60, 'party'), 'npc:b': actor(40)})
    result = perform(attack(state), 'npc:b', 'dodge', [30])
    assert result['current'] == 'player:c'


def test_extreme_blunt_damage_is_max_weapon_plus_max_db_without_damage_rng():
    rows = {'player:a': actor(70, 'party', strength=80, size=80), 'npc:b': actor(hp=40, maximum=40)}
    state = start_combat(rows)
    result = perform(attack(state, 10), 'npc:b', 'dodge', [90])
    assert damage(result['events'])['damage'] == 10  # 6 + 4, not 12 + 4.


def test_hard_success_remains_normal_damage():
    result = perform(attack(fixture(), 20), 'npc:b', 'dodge', [90, 3])
    assert damage(result['events'])['damage'] == 3


def test_extreme_impale_rolls_weapon_once_and_does_not_roll_unused_db():
    rows = {'player:a': actor(70, 'party', strength=80, size=80), 'npc:b': actor(hp=40, maximum=40)}
    result = attack(start_combat(rows), 10, 'pistol', [5])
    assert damage(result['events'])['damage'] == 15
    assert result['actors']['player:a']['weapons']['pistol']['ammo'] == 2
    assert result['pending_reaction'] is None


def test_full_armor_can_reduce_damage_to_zero():
    result = perform(attack(fixture(armor=8), 10), 'npc:b', 'dodge', [90])
    assert damage(result['events'])['damage'] == 0
    assert result['actors']['npc:b']['hp'] == 20


def test_major_wound_con_failure_causes_unconsciousness_and_ends_fight():
    result = perform(attack(fixture(hp=10, maximum=10), 10), 'npc:b', 'dodge', [90, 80])
    target = result['actors']['npc:b']
    assert target['hp'] == 4 and target['major_wound'] and target['unconscious'] and not target['dead']
    assert result['status'] == 'ended'


def test_single_blow_max_hp_is_instant_death():
    result = perform(attack(fixture(hp=5, maximum=5), 10), 'npc:b', 'dodge', [90])
    assert result['actors']['npc:b']['dead'] and result['status'] == 'ended'


def test_existing_major_wound_and_smaller_final_blow_still_causes_dying():
    row = actor(hp=2, maximum=20); row['major_wound'] = True
    state = start_combat({'player:a': actor(70, 'party'), 'npc:b': row})
    result = perform(attack(state), 'npc:b', 'dodge', [90, 3])
    assert result['actors']['npc:b']['dying'] and not result['actors']['npc:b']['dead']


def test_zero_hp_without_major_wound_is_not_death_or_dying():
    result = perform(attack(fixture(hp=2, maximum=20)), 'npc:b', 'dodge', [90, 3])
    assert result['actors']['npc:b']['unconscious']
    assert not result['actors']['npc:b']['dying'] and not result['actors']['npc:b']['dead']


def test_flee_leaves_combat_and_wait_advances_round_normally():
    state = fixture()
    state = perform(state, 'player:a', 'wait')
    state = perform(state, 'npc:b', 'wait')
    assert state['round'] == 2 and state['current'] == 'player:a'
    ended = perform(state, 'player:a', 'flee')
    assert ended['actors']['player:a']['fled'] and ended['status'] == 'ended'


@pytest.mark.parametrize('fields', [
    {'expected_revision': True}, {'expected_revision': 2}, {'actor_id': 'npc:b'},
    {'type': 'automatic_fire'}, {'target_id': 'player:a'}, {'weapon_id': 'forged'},
    {'options': {'burst': 3}}, {'damage': 999},
])
def test_invalid_intent_does_not_change_state_or_roll(fields):
    state = fixture(); before = deepcopy(state)
    intent = {'expected_revision': 0, 'actor_id': 'player:a', 'type': 'attack', 'target_id': 'npc:b', 'weapon_id': 'club', **fields}
    with pytest.raises(ValueError): resolve_action(state, intent, Rng())
    assert state == before


def test_no_pvp_or_empty_ammo_and_no_replayed_roll():
    state = fixture(); state['actors']['npc:b']['faction'] = 'party'
    with pytest.raises(ValueError): attack(state)
    state = fixture(); state['actors']['player:a']['weapons']['pistol']['ammo'] = 0
    with pytest.raises(ValueError): attack(state, weapon='pistol')
    state = attack(fixture())
    with pytest.raises(ValueError): resolve_action(state, {'expected_revision': 0, 'actor_id': 'player:a', 'type': 'wait'}, Rng())


def test_firearm_cannot_be_used_for_fight_back_and_attackers_weapon_cannot_be_borrowed():
    state = attack(fixture())
    with pytest.raises(ValueError): perform(state, 'npc:b', 'fight_back', weapon_id='pistol')
    with pytest.raises(ValueError): perform(state, 'npc:b', 'fight_back', weapon_id='unknown')
