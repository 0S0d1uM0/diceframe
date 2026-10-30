"""CoC 7e 纯战斗状态机：无 web、无 GameInstance、无存档、无全局 RNG。

标准来源：https://callofcthulhuwiki.chaosium.com/rules/combat.html 、
hit-points-wounds-and-healing.html 与 opposed-skill-rolls.html。
DEX 降序行动（同值按 actor_id 字典序）；近战无论进攻方命中与否，防守者都
获得一次反应机会（dodge / fight_back）：闪避平级防守胜、反击平级进攻方胜；
反击伤害只按普通档。枪械不结算任何反应（标准里目标不能对射击反击）。

明确未实现（不伪造）：濒死每轮末 CON 存活检定与急救/医疗稳定、掩体与扑倒、
连发/多射/超距/自动火力、战技（推倒/擒抱）、 outnumbered 奖励骰。这些一律
显式拒绝或只打事件标记。

纯函数：resolve_action 返回新状态，绝不改动传入 state；输入非法抛
ValueError 且原状态保持不变。骰值全部来自注入的 rng（提供 randint），并逐条
记录进 events。
"""

from __future__ import annotations

import copy
import re
from typing import Any

from src.rulesets.coc7e.mechanics import (
    damage_bonus,
    opposed_result,
    success_rank,
    wound_result,
)

SCHEMA_VERSION = 1
ACTION_TYPES = ("attack", "dodge", "fight_back", "wait", "flee")
REACTION_TYPES = ("dodge", "fight_back")
_ATTRIBUTES = ("str", "siz", "dex", "con")
_ALLOWED_INTENT = frozenset(
    {"expected_revision", "actor_id", "type", "target_id", "weapon_id", "options"}
)
_DICE_RE = re.compile(r"^(\d+)d(\d+)([+-](\d+))?$")


def _fail(message: str) -> None:
    raise ValueError(f"coc7e combat: {message}")


def _int(value: Any, label: str, low: int, high: int | None = None) -> int:
    upper = "inf" if high is None else str(high)
    if type(value) is not int or value < low or (high is not None and value > high):
        _fail(f"{label} must be an int in {low}..{upper}")
    return value


def _dice_parts(expr: Any, label: str) -> tuple[int, int, int]:
    match = _DICE_RE.match(str(expr or "").strip().lower())
    if not match:
        _fail(f"unsupported dice expression for {label}: {expr!r}")
    count, sides, fixed = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
    if not 1 <= count <= 20 or not 2 <= sides <= 100 or abs(fixed) > 100:
        _fail(f"dice expression out of bounds for {label}: {expr!r}")
    return count, sides, fixed


def _roll_dice(rng: Any, expr: Any, label: str) -> tuple[int, list[int]]:
    """掷标准 NdM(+/-K)；只用注入的 rng，绝不碰全局随机。"""
    count, sides, fixed = _dice_parts(expr, label)
    dice = [rng.randint(1, sides) for _ in range(count)]
    return sum(dice) + fixed, dice


def _db_max(formula: str) -> int:
    """伤害加成的最大可能值（极难钝器用），不掷骰。"""
    if formula in ("-2", "-1", "0"):
        return int(formula)
    count, sides, fixed = _dice_parts(formula, "damage bonus")
    return count * sides + fixed


def _is_melee(weapon: dict) -> bool:
    return weapon["ammo"] is None


def _melee_weapons(actor: dict) -> list[tuple[str, dict]]:
    """防守者自有的、技能可用的近战武器（反击候选）。"""
    return [
        (weapon_id, weapon)
        for weapon_id, weapon in actor["weapons"].items()
        if _is_melee(weapon) and weapon["skill"] and weapon["skill"] in actor["skills"]
    ]


def _can_act(actor: dict) -> bool:
    """主动行动权：未死亡、未昏迷、未濒死、未逃离。"""
    return (not actor["dead"] and not actor["dying"] and not actor["unconscious"]
            and not actor["fled"] and actor["hp"] > 0)


def _can_react(actor: dict) -> bool:
    """Only a conscious, active combatant may answer a reaction window."""
    return _can_act(actor)


def _order_of(actors: dict[str, dict]) -> list[str]:
    """可行动者顺序（DEX 降序，同值按 actor_id 字典序）。"""
    eligible = [aid for aid, actor in actors.items() if _can_act(actor)]
    return sorted(eligible, key=lambda aid: (-actors[aid]["attributes"]["dex"], aid))


def start_combat(actors: dict[str, dict]) -> dict:
    """由服务端可信 actor 记录建立战斗状态（深拷贝，之后不再回读输入）。"""
    if not isinstance(actors, dict) or not actors:
        _fail("actors must be a non-empty dict")
    normalized: dict[str, dict] = {}
    for raw_id, record in actors.items():
        actor_id = str(raw_id or "")
        if ":" not in actor_id or actor_id.split(":", 1)[0] not in ("player", "npc"):
            _fail(f"actor id must be player:<uid> or npc:<uid>: {raw_id!r}")
        if not isinstance(record, dict):
            _fail(f"actor {actor_id} record must be an object")
        attributes = record.get("attributes")
        if not isinstance(attributes, dict):
            _fail(f"actor {actor_id} requires an attributes object")
        attrs = {
            key: _int(attributes.get(key), f"{actor_id}.attributes.{key}", 1, 99)
            for key in _ATTRIBUTES
        }
        max_hp = _int(record.get("max_hp"), f"{actor_id}.max_hp", 1)
        hp = _int(record.get("hp"), f"{actor_id}.hp", 0, max_hp)
        skills = record.get("skills")
        if not isinstance(skills, dict):
            _fail(f"actor {actor_id} requires a skills object")
        norm_skills = {
            str(name): _int(value, f"{actor_id}.skills.{name}", 0, 100)
            for name, value in skills.items()
        }
        weapons = record.get("weapons")
        if not isinstance(weapons, dict):
            _fail(f"actor {actor_id} requires a weapons object")
        norm_weapons: dict[str, dict] = {}
        for weapon_id, weapon in weapons.items():
            if not isinstance(weapon, dict):
                _fail(f"{actor_id} weapon {weapon_id} must be an object")
            ammo = weapon.get("ammo")
            if ammo is not None:
                ammo = _int(ammo, f"{actor_id} weapon {weapon_id}.ammo", 0)
            norm_weapons[str(weapon_id)] = {
                "damage_dice": str(weapon.get("damage_dice") or ""),
                "skill": str(weapon.get("skill") or ""),
                "impale": weapon.get("impale") is True,
                "uses_db": weapon.get("uses_db") is True,
                "ammo": ammo,
            }
            _dice_parts(norm_weapons[str(weapon_id)]['damage_dice'], 'weapon damage')
        # 起始 0 HP 且没有重伤标记：只是昏迷，不是死亡。
        normalized[actor_id] = {
            "name": str(record.get("name") or actor_id),
            "faction": str(record.get("faction") or actor_id),
            "attributes": attrs,
            "hp": hp,
            "max_hp": max_hp,
            "armor": _int(record.get("armor", 0), f"{actor_id}.armor", 0),
            "skills": norm_skills,
            "weapons": norm_weapons,
            "major_wound": record.get("major_wound") is True,
            "dying": hp <= 0 and record.get("major_wound") is True,
            "unconscious": hp <= 0 or record.get('unconscious') is True,
            "dead": record.get('dead') is True,
            "fled": False,
        }
    order = _order_of(normalized)
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "status": "active" if order else "ended",
        "round": 1,
        "order": order,
        "current": order[0] if order else None,
        "turn_order": sorted(normalized, key=lambda aid: (-normalized[aid]['attributes']['dex'], aid)),
        "actors": normalized,
        "pending_reaction": None,
        "events": [],
        "summary": None,
    }


def _validate_intent(state: dict, intent: dict) -> tuple[str, list[dict]]:
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        _fail("unsupported state schema")
    if state.get("status") != "active":
        _fail("combat is not active")
    if not isinstance(intent, dict):
        _fail("intent must be an object")
    extra = set(intent) - _ALLOWED_INTENT
    if extra:
        _fail(f"unsupported intent fields: {sorted(extra)}")
    revision = _int(intent.get("expected_revision"), "expected_revision", 0)
    if revision != state["revision"]:
        _fail(f"stale revision {revision} != {state['revision']} (double resolution?)")
    actor_id = str(intent.get("actor_id") or "")
    actor = state["actors"].get(actor_id)
    if actor is None:
        _fail(f"unknown actor {actor_id!r}")
    action_type = str(intent.get("type") or "")
    if action_type not in ACTION_TYPES:
        _fail(f"unsupported action type: {action_type!r}")
    pending = state.get("pending_reaction")
    if pending:
        # 反应窗口：只有被点名的防守者能用 dodge/fight_back 回应，其余一律拒绝。
        if action_type not in REACTION_TYPES:
            _fail(f"a pending reaction blocks action {action_type!r}")
        if actor_id != pending["target_id"]:
            _fail(f"the pending reaction belongs to {pending['target_id']}")
        if not _can_react(actor):
            _fail(f"actor {actor_id} cannot react in its current condition")
    else:
        if action_type in REACTION_TYPES:
            _fail("no pending reaction to answer")
        # 主动行动只属于当前行动者，且必须仍具行动权。
        if actor_id != state.get("current"):
            _fail(f"it is {state.get('current')}'s turn, not {actor_id}'s")
        if not _can_act(actor):
            _fail(f"actor {actor_id} cannot act in its current condition")
    return action_type, []


def _end_state(next_state: dict, events: list[dict], reason: str) -> dict:
    """战斗收尾：清空反应窗口与临时字段，写 summary。"""
    order = _order_of(next_state["actors"])
    next_state["order"] = order
    next_state["status"] = "ended"
    next_state["current"] = None
    next_state["pending_reaction"] = None
    next_state.pop("_resume_actor", None)
    next_state["summary"] = {
        "reason": reason,
        "survivors": [aid for aid, actor in next_state["actors"].items()
                      if not actor["dead"] and not actor["fled"]],
    }
    next_state["events"] = events
    return next_state


def _advance(next_state: dict, events: list[dict]) -> dict:
    """把行动权交给下一名可行动者；轮次收尾则 round+1；判定战斗结束。"""
    order = _order_of(next_state["actors"])
    next_state["order"] = order
    factions = {next_state["actors"][aid]["faction"] for aid in order}
    if not order:
        return _end_state(next_state, events, "no_active_combatants")
    if len(factions) <= 1:
        # 一方再无可行动者（死亡/昏迷/濒死/逃离）即结束。
        return _end_state(next_state, events, "single_faction_remains")
    previous = str(next_state.get('current') or '')
    full_order = next_state.get('turn_order', order)
    index = full_order.index(previous)
    for offset in range(1, len(full_order) + 1):
        position = (index + offset) % len(full_order)
        if full_order[position] in order:
            holder = full_order[position]
            if index + offset >= len(full_order):
                next_state['round'] += 1
                events.append({'type': 'combat.round_advanced', 'round': next_state['round']})
            break
    next_state["current"] = holder
    next_state["events"] = events
    return next_state


def _finish_action(next_state: dict, events: list[dict]) -> dict:
    """常规推进；若刚结束一次反应，行动权接回进攻者的原顺序位（不从防守者索引跳人）。"""
    resume = next_state.pop("_resume_actor", None)
    if resume is not None:
        next_state['current'] = resume
    return _advance(next_state, events)


def _normal_db(next_state: dict, attacker_id: str, rng: Any | None
               ) -> tuple[str, int, list[int]]:
    """正常伤害加成；公式为常数（含 0 与负值）时不掷骰，避免多余随机。"""
    attributes = next_state["actors"][attacker_id]["attributes"]
    formula = damage_bonus(attributes["str"], attributes["siz"])["formula"]
    if formula in ("-2", "-1", "0"):
        return formula, int(formula), []
    if rng is None:
        return formula, 0, []
    total, dice = _roll_dice(rng, formula, "damage bonus")
    return formula, total, dice


def _damage_roll(next_state: dict, attacker_id: str, weapon: dict, rank: int,
                 rng: Any, capped: bool) -> tuple[int, dict[str, Any]]:
    """伤害骰（标准）：
    - 反击（capped）：只按普通档；
    - 极难或大成功（rank>=3）+ 钝器：武器最大骰 + DB 最大值；
    - 极难或大成功 + 穿刺：武器最大骰 + 正常 DB + 再投一次武器骰；
    - 其余：正常武器骰 + 正常 DB。
    每种模式最多掷一次 DB 骰（常数档 -2/-1/0 不掷）。
    """
    count, sides, fixed = _dice_parts(weapon["damage_dice"], "weapon damage")
    weapon_max = count * sides + fixed
    uses_db = weapon["uses_db"]
    if capped:
        formula, normal_db, db_dice = _normal_db(next_state, attacker_id, rng if uses_db else None)
        total, dice = _roll_dice(rng, weapon["damage_dice"], "weapon damage")
        applied = normal_db if uses_db else 0
        total += applied
        detail = {"mode": "counter_attack_normal", "success_rank": rank,
                  "weapon_damage": weapon["damage_dice"], "damage_bonus": formula,
                  "weapon_roll": sum(dice), "db_applied": applied, "db_dice": db_dice}
    elif rank >= 3 and not weapon["impale"]:
        formula = damage_bonus(next_state["actors"][attacker_id]["attributes"]["str"],
                               next_state["actors"][attacker_id]["attributes"]["siz"])["formula"]
        db_max = _db_max(formula) if uses_db else 0
        total = weapon_max + db_max
        detail = {"mode": "severe_or_extreme_blunt", "success_rank": rank,
                  "weapon_damage": weapon["damage_dice"], "damage_bonus": formula,
                  "weapon_max": weapon_max, "db_max": db_max}
    elif rank >= 3:
        # 穿刺：武器伤害取最大值，另重掷一次武器骰；DB 按普通方式掷一次。
        formula, db_value, db_dice = _normal_db(next_state, attacker_id, rng if uses_db else None)
        extra, extra_dice = _roll_dice(rng, weapon["damage_dice"], "impale reroll")
        applied = db_value if uses_db else 0
        total = weapon_max + applied + extra
        detail = {"mode": "severe_or_extreme_impale", "success_rank": rank,
                  "weapon_damage": weapon["damage_dice"], "damage_bonus": formula,
                  "weapon_max": weapon_max, "reroll": sum(extra_dice),
                  "reroll_dice": extra_dice, "db_applied": applied, "db_dice": db_dice}
    else:
        formula, normal_db, db_dice = _normal_db(next_state, attacker_id, rng if uses_db else None)
        total, dice = _roll_dice(rng, weapon["damage_dice"], "weapon damage")
        applied = normal_db if uses_db else 0
        total += applied
        detail = {"mode": "normal", "success_rank": rank,
                  "weapon_damage": weapon["damage_dice"], "damage_bonus": formula,
                  "weapon_roll": sum(dice), "db_applied": applied, "db_dice": db_dice}
    return max(0, total), detail


def _apply_damage(next_state: dict, target_id: str, raw_damage: int, rng: Any,
                  events: list[dict]) -> None:
    actor = next_state["actors"][target_id]
    armor = actor["armor"]
    damage = max(0, raw_damage - armor)  # 护甲全额扣除，可为 0（不强制保底 1）
    outcome = wound_result(actor["max_hp"], actor["hp"], damage,
                           major_wound=actor["major_wound"])
    events.append({
        "type": "combat.damage", "target_id": target_id, "raw_damage": raw_damage,
        "armor_applied": armor, "damage": damage, "hp_before": actor["hp"],
        "hp_after": outcome["hp"], "major_wound": outcome["major_wound"],
        "unconscious": outcome["unconscious"], "dying": outcome["dying"],
        "dead": outcome["dead"],
    })
    actor["hp"] = outcome["hp"]
    actor["major_wound"] = bool(outcome["major_wound"])
    actor["dying"] = bool(outcome["dying"])
    if outcome["dead"]:
        actor["dead"] = True
        actor["unconscious"] = True
        events.append({"type": "combat.actor_dead", "actor_id": target_id,
                       "reason": "single_blow_ge_max_hp"})
    elif outcome["hp"] == 0:
        # 标准：未受重伤跌到 0 HP 只是昏迷；带重伤才进入濒死。
        actor["unconscious"] = True
        if outcome["major_wound"]:
            events.append({"type": "combat.actor_dying", "actor_id": target_id})
        else:
            events.append({"type": "combat.actor_unconscious", "actor_id": target_id,
                           "major_wound": False})
    elif outcome["unconscious"]:
        events.append({"type": "combat.actor_unconscious", "actor_id": target_id,
                       "reason": "hp_zero"})
    if outcome["con_check_required"]:
        # 标准：受重伤必须 CON 检定，失败即昏迷。存活检定与急救不在本子集内。
        con = actor["attributes"]["con"]
        roll = rng.randint(1, 100)
        success = roll <= con
        events.append({"type": "combat.con_check", "actor_id": target_id, "roll": roll,
                       "skill": con, "success": success, "reason": "major_wound"})
        if not success:
            actor["unconscious"] = True
            events.append({"type": "combat.actor_unconscious", "actor_id": target_id,
                           "reason": "failed_major_wound_con_check"})


def _strike(next_state: dict, attacker_id: str, target_id: str, weapon: dict,
            rank: int, rng: Any, events: list[dict], *, capped: bool = False) -> None:
    damage, detail = _damage_roll(next_state, attacker_id, weapon, rank, rng, capped)
    events.append({"type": "combat.damage_roll", "attacker_id": attacker_id,
                   "target_id": target_id, **detail})
    _apply_damage(next_state, target_id, damage, rng, events)


def _offer_reaction(next_state: dict, attacker_id: str, target_id: str, weapon_id: str,
                    attack_roll: int, attack_skill: str, rank: int, rng: Any,
                    events: list[dict]) -> dict:
    defender = next_state["actors"][target_id]
    attacker_weapon = next_state["actors"][attacker_id]["weapons"][weapon_id]
    if not _can_react(defender):
        events.append({"type": "combat.reaction_declined", "target_id": target_id,
                       "reason": "defender cannot react in its current condition"})
        if rank:
            _strike(next_state, attacker_id, target_id, attacker_weapon, rank, rng, events)
        return _advance(next_state, events)
    dodge = defender["skills"].get("dodge")
    counter_weapons = _melee_weapons(defender)
    if dodge is None and not counter_weapons:
        events.append({"type": "combat.reaction_declined", "target_id": target_id,
                       "reason": "defender has neither a dodge skill nor a usable melee weapon"})
        if rank:
            _strike(next_state, attacker_id, target_id, attacker_weapon, rank, rng, events)
        return _advance(next_state, events)
    next_state["pending_reaction"] = {
        "attacker_id": attacker_id, "target_id": target_id, "weapon_id": weapon_id,
        "attack_roll": attack_roll,
        "attack_skill": next_state['actors'][attacker_id]['skills'][attack_skill], "attack_rank": rank,
        "counter_weapon_ids": [candidate_id for candidate_id, _ in counter_weapons],
    }
    # 反应窗口打开时，行动权暂时让给防守者；结算后回到进攻者的原顺序位。
    next_state["current"] = target_id
    return next_state


def _resolve_attack(next_state: dict, intent: dict, rng: Any, events: list[dict]) -> dict:
    actor_id = str(intent["actor_id"])
    attacker = next_state["actors"][actor_id]
    target_id = str(intent.get("target_id") or "")
    target = next_state["actors"].get(target_id)
    if target is None or target_id == actor_id:
        _fail(f"invalid attack target {target_id!r}")
    if target["dead"] or target["fled"]:
        _fail(f"target {target_id} is not a valid target")
    if attacker["faction"] == target["faction"]:
        _fail("friendly fire is not allowed (no PvP by default)")
    weapon_id = str(intent.get("weapon_id") or "")
    weapon = attacker["weapons"].get(weapon_id)
    if weapon is None:
        _fail(f"actor {actor_id} has no weapon {weapon_id!r}")
    skill_name = weapon["skill"]
    if not skill_name or skill_name not in attacker["skills"]:
        _fail(f"actor {actor_id} cannot use weapon {weapon_id} (missing skill {skill_name!r})")
    if intent.get("options"):
        _fail(f"unsupported combat options in this phase: {sorted(intent['options'])}")
    firearm = not _is_melee(weapon)
    if firearm:
        if weapon["ammo"] <= 0:
            _fail(f"weapon {weapon_id} is out of ammo")
        next_state["actors"][actor_id]["weapons"][weapon_id]["ammo"] = weapon["ammo"] - 1
        events.append({"type": "combat.ammo_spent", "actor_id": actor_id,
                       "weapon_id": weapon_id, "ammo_left": weapon["ammo"] - 1})
    attack_roll = rng.randint(1, 100)
    rank = success_rank(attack_roll, attacker["skills"][skill_name])
    events.append({"type": "combat.attack", "actor_id": actor_id, "target_id": target_id,
                   "weapon_id": weapon_id, "firearm": firearm, "skill": skill_name,
                   "roll": attack_roll, "success_rank": rank})
    if firearm:
        # 标准：被射击者不能反击；闪避/扑倒掩体未建模，只打标记。
        events.append({"type": "combat.reaction_unsupported", "target_id": target_id,
                       "reason": "firearm reactions (dodge / dive for cover) are not modeled"})
        if rank == 0:
            events.append({"type": "combat.attack_missed", "actor_id": actor_id,
                           "target_id": target_id})
        else:
            _strike(next_state, actor_id, target_id, weapon, rank, rng, events)
        return _advance(next_state, events)
    if rank == 0:
        events.append({"type": "combat.attack_missed", "actor_id": actor_id,
                       "target_id": target_id})
    # 标准：近战无论进攻方是否命中，防守者都有反应机会（反击也可能在对方失手时成立）。
    return _offer_reaction(next_state, actor_id, target_id, weapon_id, attack_roll,
                           skill_name, rank, rng, events)


def _resolve_reaction(next_state: dict, intent: dict, rng: Any, events: list[dict]) -> dict:
    pending = next_state["pending_reaction"]
    defender_id = str(intent["actor_id"])
    attacker_id = pending["attacker_id"]
    reaction = str(intent["type"])
    defender = next_state["actors"][defender_id]
    if reaction == "dodge":
        skill_name = "dodge"
        skill = defender["skills"].get(skill_name)
        if skill is None:
            _fail(f"actor {defender_id} has no dodge skill")
        counter_weapon = None
    else:
        requested = str(intent.get("weapon_id") or "")
        candidates = dict(_melee_weapons(defender))
        if requested:
            counter_weapon = candidates.get(requested)
            if counter_weapon is None:
                _fail(f"actor {defender_id} cannot fight back with {requested!r} "
                      "(needs a melee weapon whose skill it owns)")
        else:
            if len(candidates) != 1:
                _fail("fight_back requires an explicit weapon_id when the defender "
                      "has more than one usable melee weapon")
            counter_weapon = next(iter(candidates.values()))
        # 反击技能来自防守者所选武器自身声明（如 fighting_brawl），绝不沿用进攻方武器。
        skill_name = counter_weapon["skill"]
        skill = defender["skills"][skill_name]
    defend_roll = rng.randint(1, 100)
    outcome = opposed_result(pending["attack_roll"], pending["attack_skill"],
                             defend_roll, skill, mode=reaction)
    events.append({"type": "combat.reaction", "actor_id": defender_id, "mode": reaction,
                   "skill": skill_name, "roll": defend_roll,
                   "success_rank": success_rank(defend_roll, skill), "outcome": outcome})
    next_state["pending_reaction"] = None
    attacker_weapon = next_state["actors"][attacker_id]["weapons"][pending["weapon_id"]]
    if outcome == "defender":
        events.append({"type": "combat.attack_negated", "attacker_id": attacker_id,
                       "target_id": defender_id, "mode": reaction})
        if reaction == "fight_back" and _can_react(next_state["actors"][attacker_id]):
            # 反击命中：只按普通档伤害（标准：反击最多普通伤害）。
            _strike(next_state, defender_id, attacker_id, counter_weapon, 1, rng, events,
                    capped=True)
    elif outcome == "attacker":
        if pending["attack_rank"] == 0:
            # 双方都失手且按 mode 判给进攻方：不造成伤害。
            events.append({"type": "combat.attack_negated", "attacker_id": attacker_id,
                           "target_id": defender_id, "mode": "attack_failed"})
        else:
            _strike(next_state, attacker_id, defender_id, attacker_weapon,
                    pending["attack_rank"], rng, events)
    else:
        events.append({"type": "combat.attack_negated", "attacker_id": attacker_id,
                       "target_id": defender_id, "mode": "tie"})
    # 反应结束：行动权接回进攻者（其原行动尚未轮转），不能从防守者索引继续跳人。
    next_state["_resume_actor"] = attacker_id
    return _finish_action(next_state, events)


def resolve_action(state: dict, intent: dict, rng: Any) -> dict:
    """结算一个行动并返回新状态；传入的 state 永不被修改。"""
    if rng is None or not callable(getattr(rng, "randint", None)):
        _fail("rng must provide randint(low, high)")
    action_type, events = _validate_intent(state, intent)
    next_state = copy.deepcopy(state)
    next_state["events"] = events
    next_state["revision"] = int(state["revision"]) + 1
    if action_type == "attack":
        return _resolve_attack(next_state, intent, rng, events)
    if action_type in REACTION_TYPES:
        return _resolve_reaction(next_state, intent, rng, events)
    actor_id = str(intent["actor_id"])
    if intent.get("options"):
        _fail(f"unsupported combat options in this phase: {sorted(intent['options'])}")
    if action_type == "flee":
        # 逃离：退出本轮与后续排队，但仍是生者（不计入死亡）。
        next_state["actors"][actor_id]["fled"] = True
    events.append({"type": f"combat.{action_type}", "actor_id": actor_id})
    return _finish_action(next_state, events)
