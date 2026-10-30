"""CoC/理智类疯狂状态处理。"""

from __future__ import annotations

import logging
import random

from src.engine.game_instance import GameInstance
from src.rulesets.sanity import apply_sanity_loss

logger = logging.getLogger("trpg")


class MadnessTracker:
    """根据理智损失应用和推进疯狂状态。"""

    def apply_madness(self, instance: GameInstance, uid: str, character_sheet: dict, loss: int,
                      *, rng: random.Random | None = None) -> None:
        """根据理智值损失量判断疯狂状态。"""
        apply_sanity_loss(instance, uid, character_sheet, loss, rng=rng)

    def tick_madness(self, instance: GameInstance) -> None:
        """每轮结束时减少疯狂状态回合数。"""
        for uid, player in instance.players.items():
            character_sheet = player.get("character_sheet", {})
            madness = character_sheet.get("madness")
            if not madness or madness.get("type") is None:
                continue
            if 'remaining_rounds' not in madness:
                # Ruleset-owned hours/day durations are not legacy round timers.
                continue
            madness["remaining_rounds"] = madness.get("remaining_rounds", 0) - 1
            name = player.get("character_name", uid)
            if madness["remaining_rounds"] <= 0:
                logger.info("%s 疯狂状态结束: type=%s", name, madness.get("type"))
                character_sheet["madness"] = {"type": None, "remaining_rounds": 0, "symptom": ""}
            else:
                logger.debug("%s 疯狂状态剩余 %d 轮", name, madness["remaining_rounds"])
