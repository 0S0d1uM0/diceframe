"""CoC SAN events with distinct success/failure losses and daily accounting."""
from __future__ import annotations
import re

from src.engine import dice_rng
from src.engine.modules import progression_state
from .mechanics import sanity_transition, success_rank

_LOSS = re.compile(r'^(?:0|[1-9]\d?|[1-9]d(?:[2-9]|[1-9]\d|100))(?:[+]\d{1,2})?$')


def _loss(formula: str, *, maximum: bool = False) -> int:
    if not _LOSS.fullmatch(formula):
        raise ValueError('SAN loss must be a bounded nonnegative literal or dice expression')
    if not maximum:
        return int(formula) if formula.isdigit() else dice_rng.roll(formula).total
    base, _, modifier = formula.partition('+')
    if 'd' in base:
        count, sides = map(int, base.split('d'))
        return count * sides + int(modifier or 0)
    return int(base) + int(modifier or 0)


def apply_event(instance, uid: str, update: dict) -> None:
    value = update.get('san_check_loss')
    if not value:
        return
    # Validate both sides before rolling; malformed events never invent 1d6.
    parts = str(value).lower().replace(' ', '').split('/')
    if len(parts) != 2 or any(not _LOSS.fullmatch(part) for part in parts):
        raise ValueError('CoC SAN_CHECK requires success/failure loss, e.g. 0/1d6')
    sheet = instance.get_character_sheet(uid)
    current = int(sheet.get('sanity', 0))
    if current <= 0:
        return
    event_id = f'{instance.run_id}:{progression_state.round_value(instance)}:{uid}'
    previous = sheet.get('coc_sanity', {})
    if previous.get('last_event_id') == event_id:
        return
    day = int(instance.world_state.get('clock', {}).get('day', 1))
    same_day = previous.get('day') == day
    start = int(previous.get('daily_start_san', current)) if same_day else current
    accumulated = int(previous.get('daily_loss', 0)) if same_day else 0
    rolled = dice_rng.roll('1d100').total
    succeeded = success_rank(rolled, current) > 0
    fumble = rolled == 100 or (current < 50 and rolled >= 96)
    formula = parts[0] if succeeded else parts[1]
    loss = _loss(formula, maximum=fumble)
    transition = sanity_transition(current, loss, start, accumulated,
        intelligence=int(sheet['attributes']['int']))
    int_roll = None
    if transition['needs_int_check']:
        int_roll = dice_rng.roll('1d100').total
        transition = sanity_transition(current, loss, start, accumulated, int_roll=int_roll,
            intelligence=int(sheet['attributes']['int']))
    sheet['sanity'] = transition['sanity']
    sheet['coc_sanity'] = {'day': day, 'daily_start_san': start,
        'daily_loss': transition['daily_loss'], 'last_event_id': event_id,
        'last_check': {'roll': rolled, 'success': succeeded, 'formula': formula,
                       'loss': min(current, loss), 'int_roll': int_roll}}
    if transition['permanent']:
        sheet['deceased'] = True  # Existing player-control boundary disables this investigator.
        sheet['death_cause'] = '永久疯狂'
        sheet['madness'] = {'type': 'permanent', 'symptom': '永久疯狂，调查员退场'}
    elif transition['indefinite'] or transition['temporary']:
        hours = dice_rng.roll('1d10').total if transition['temporary'] else None
        rounds = dice_rng.roll('1d10').total
        sheet['madness'] = {'type': 'indefinite' if transition['indefinite'] else 'temporary',
            'bout_rounds': rounds, 'duration_hours': hours, 'onset_day': day,
            'symptom': '疯狂发作；由KP裁定非恶意行为，不允许攻击、背叛或偷窃队友'}
