"""CoC 7e 纯规则数学：无 RNG、无存档、无外部依赖。

来源（标准 7e）：Damage Bonus and Build Table 与 Move Rate，见
https://cocwiki.chaosium.com/investigators/step-two-secondary-attributes.html
本模块只做确定性换算；骰子与状态写入由调用方（引擎/runtime）负责。
"""

from __future__ import annotations


def _integer(value: int, label: str, low: int, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError(f'{label} is outside its integer range')
    return value


def success_rank(roll: int, skill: int) -> int:
    _integer(roll, 'roll', 1, 100)
    _integer(skill, 'skill', 0, 100)
    if roll == 1:
        return 4
    if roll == 100 or (skill < 50 and roll >= 96) or roll > skill:
        return 0
    return 3 if roll <= skill // 5 else 2 if roll <= skill // 2 else 1


def opposed_result(attack_roll: int, attack_skill: int, defend_roll: int, defend_skill: int,
                   *, mode: str = 'opposed') -> str:
    if mode not in ('opposed', 'dodge', 'fight_back'):
        raise ValueError('Unsupported opposed-roll mode')
    attack = success_rank(attack_roll, attack_skill)
    defense = success_rank(defend_roll, defend_skill)
    if attack == defense == 0:
        return 'tie'
    if attack != defense:
        return 'attacker' if attack > defense else 'defender'
    if mode == 'dodge':
        return 'defender'
    if mode == 'fight_back':
        return 'attacker'
    if attack_skill == defend_skill:
        return 'tie'
    return 'attacker' if attack_skill > defend_skill else 'defender'


def wound_result(max_hp: int, current_hp: int, damage: int, *, major_wound: bool = False) -> dict:
    _integer(max_hp, 'max_hp', 1)
    _integer(current_hp, 'current_hp', 0, max_hp)
    _integer(damage, 'damage', 0)
    if type(major_wound) is not bool:
        raise ValueError('major_wound must be boolean')
    new_major = damage * 2 >= max_hp
    major = major_wound or new_major
    hp = max(0, current_hp - damage)
    dead = damage >= max_hp
    return {'hp': hp, 'major_wound': major, 'unconscious': hp == 0 or dead,
            'dying': hp == 0 and major and not dead, 'dead': dead,
            'con_check_required': new_major and not dead and hp > 0}


def sanity_transition(current_san: int, loss: int, daily_start_san: int, daily_loss: int,
                      *, int_roll: int | None = None, intelligence: int = 50) -> dict:
    _integer(current_san, 'current_san', 0, 99)
    _integer(loss, 'loss', 0)
    _integer(daily_start_san, 'daily_start_san', 0, 99)
    _integer(daily_loss, 'daily_loss', 0)
    _integer(intelligence, 'intelligence', 1, 100)
    if int_roll is not None:
        _integer(int_roll, 'int_roll', 1, 100)
    actual_loss = min(current_san, loss)
    sanity = current_san - actual_loss
    cumulative = daily_loss + actual_loss
    permanent = sanity == 0
    indefinite = not permanent and cumulative >= max(1, daily_start_san // 5)
    eligible = actual_loss >= 5 and not permanent and not indefinite
    return {'sanity': sanity, 'daily_loss': cumulative, 'permanent': permanent,
            'indefinite': indefinite, 'temporary': eligible and int_roll is not None and int_roll <= intelligence,
            'needs_int_check': eligible and int_roll is None}

# (总和上界, damage bonus 公式, build)。上界之后的档位在 damage_bonus 里推导。
_DAMAGE_BANDS: tuple[tuple[int, str, int], ...] = (
    (64, "-2", -2),
    (84, "-1", -1),
    (124, "0", 0),
    (164, "1d4", 1),
    (204, "1d6", 2),
)
_BAND_STEP = 80          # 205 起每 +80 一档：3/2d6, 4/3d6, ...
_MIN_ATTRIBUTE = 1
_MIN_AGE = 15
_MAX_AGE = 89


def _attribute(value: object, name: str) -> int:
    """严格属性校验：拒绝 bool、非 int 与非正数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < _MIN_ATTRIBUTE:
        raise ValueError(f"{name} must be >= {_MIN_ATTRIBUTE}, got {value}")
    return value


def damage_bonus(strength: int, size: int) -> dict[str, object]:
    """由 STR+SIZ 总和给出 build 与 damage bonus 公式（标准表 + 每80外推）。"""
    total = _attribute(strength, "strength") + _attribute(size, "size")
    for upper, formula, build in _DAMAGE_BANDS:
        if total <= upper:
            return {"build": build, "formula": formula}
    extra = (total - _DAMAGE_BANDS[-1][0] - 1) // _BAND_STEP + 1
    return {"build": 2 + extra, "formula": f"{1 + extra}d6"}


def movement(strength: int, dexterity: int, size: int, age: int) -> int:
    """核心 MOVE（7/8/9）叠加年龄减值，40 岁起每十年 -1，下限 1。"""
    str_value = _attribute(strength, "strength")
    dex_value = _attribute(dexterity, "dexterity")
    siz_value = _attribute(size, "size")
    if isinstance(age, bool) or not isinstance(age, int):
        raise TypeError(f"age must be an int, got {type(age).__name__}")
    if not _MIN_AGE <= age <= _MAX_AGE:
        raise ValueError(f"age must be in {_MIN_AGE}..{_MAX_AGE}, got {age}")

    if str_value < siz_value and dex_value < siz_value:
        base = 7
    elif str_value > siz_value and dex_value > siz_value:
        base = 9
    else:
        base = 8
    decade = min(max(0, age // 10 - 3), 5)  # 40/50/60/70/>=80 -> 1..5
    return max(1, base - decade)
