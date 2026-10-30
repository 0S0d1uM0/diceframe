"""Narrative hazards use CoC injury thresholds; healing requires a future owner."""
from src.engine import dice_rng
from src.engine.modules import progression_state
from .mechanics import wound_result


def apply_injury(instance, uid: str, update: dict) -> None:
    sheet = instance.get_character_sheet(uid)
    delta = update.get('hp_change')
    if type(delta) is not int or delta >= 0 or sheet.get('deceased'):
        update.pop('hp_change', None)
        return
    # A hazard amount is adjudicated by the Keeper, but every resulting injury,
    # CON roll and death threshold is settled by rules. Combat uses its own RNG.
    outcome = wound_result(int(sheet['max_hp']), int(sheet['hp']), -delta,
                           major_wound=bool(sheet.get('major_wound')))
    previous_hp = sheet['hp']
    previously_unconscious = bool(sheet.get('unconscious'))
    sheet.update({key: outcome[key] for key in ('hp', 'major_wound', 'dying')})
    sheet['unconscious'] = previously_unconscious or outcome['unconscious']
    if outcome['con_check_required']:
        roll = dice_rng.roll('1d100').total
        sheet['coc_last_injury_check'] = {'roll': roll, 'con': sheet['attributes']['con']}
        sheet['unconscious'] |= roll > int(sheet['attributes']['con'])
    if outcome['dead']:
        sheet['deceased'] = True
        sheet['death_cause'] = '单次伤害达到最大生命值'
        sheet['death_round'] = progression_state.round_value(instance)
    sheet['status'] = 'dead' if sheet.get('deceased') else 'downed' if sheet['unconscious'] else 'normal'
    update['hp_change'] = sheet['hp'] - previous_hp
