"""Boundary tests for src/rulesets/coc7e/mechanics.py (damage_bonus, movement).

纯函数边界覆盖：档位切换点、MOVE 三档与年龄阶梯、严格类型/范围拒绝。
不依赖引擎、RNG 或存档。
"""

from __future__ import annotations

import pytest

from src.rulesets.coc7e.mechanics import damage_bonus, movement


@pytest.mark.parametrize(
    "strength,size,build,formula",
    [
        (32, 32, -2, "-2"),      # 64 = 首档上界
        (33, 32, -1, "-1"),      # 65 进入第二档
        (42, 42, -1, "-1"),      # 84 = 第二档上界
        (43, 42, 0, "0"),        # 85 进入无加成档
        (62, 62, 0, "0"),        # 124
        (63, 62, 1, "1d4"),      # 125
        (82, 82, 1, "1d4"),      # 164
        (83, 82, 2, "1d6"),      # 165
        (102, 102, 2, "1d6"),    # 204 = 标准表末档
        (103, 102, 3, "2d6"),    # 205 起外推第一档
        (142, 142, 3, "2d6"),    # 284 = 外推档上界
        (143, 142, 4, "3d6"),    # 285 起再进一档
    ],
)
def test_damage_bonus_bands(strength: int, size: int, build: int, formula: str) -> None:
    assert damage_bonus(strength, size) == {"build": build, "formula": formula}


@pytest.mark.parametrize(
    "strength,dexterity,size,age,mov",
    [
        (50, 50, 60, 30, 7),     # STR、DEX 均小于 SIZ
        (50, 50, 50, 30, 8),     # 相等走中间档
        (60, 60, 50, 30, 9),     # 均大于 SIZ
        (50, 60, 55, 30, 8),     # 一高一低走中间档
        (60, 50, 55, 30, 8),
        (50, 50, 60, 39, 7),     # 40 岁前无减值
        (50, 50, 60, 40, 6),     # 40 起 -1
        (50, 50, 60, 49, 6),     # 仍按 40 档
        (50, 50, 60, 50, 5),     # 50 起 -2
        (50, 50, 60, 79, 3),     # 仍按 70 档 -4
        (50, 50, 60, 80, 2),     # base 7 minus five
        (50, 50, 60, 89, 2),
        (60, 60, 50, 80, 4),     # base 9 减 5
        (50, 50, 50, 80, 3),
    ],
)
def test_movement_bands(
    strength: int, dexterity: int, size: int, age: int, mov: int,
) -> None:
    assert movement(strength, dexterity, size, age) == mov


@pytest.mark.parametrize("strength,size", [(True, 50), (50, False)])
def test_damage_bonus_rejects_bool(strength: object, size: object) -> None:
    with pytest.raises(TypeError):
        damage_bonus(strength, size)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "strength,size",
    [(50.0, 50), (50, "60"), (0, 50), (-1, 50), (50, 0), (50, -5)],
)
def test_damage_bonus_rejects_bad_attributes(
    strength: object, size: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        damage_bonus(strength, size)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "strength,dexterity,size,age",
    [
        (True, 50, 50, 30), (50, True, 50, 30), (50, 50, True, 30),
        (50, 50, 50, True),
        (50.0, 50, 50, 30), (50, 50, 50, 30.0), (50, 50, 50, "30"),
        (0, 50, 50, 30), (-1, 50, 50, 30), (50, 0, 50, 30), (50, 50, -1, 30),
    ],
)
def test_movement_rejects_bad_types_and_attributes(
    strength: object, dexterity: object, size: object, age: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        movement(strength, dexterity, size, age)  # type: ignore[arg-type]


@pytest.mark.parametrize("age", [14, 90, 0, -1, 2026])
def test_movement_rejects_out_of_range_age(age: int) -> None:
    with pytest.raises(ValueError):
        movement(50, 50, 50, age)
