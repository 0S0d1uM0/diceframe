"""Explicit CoC entry; capabilities reflect implemented surfaces only."""
from __future__ import annotations
from copy import deepcopy
import json
from typing import Any

from src.adventures.graph_v2 import ADVENTURE_GRAPH_FORMAT_V2
from src.rulesets.contracts import RulesetCapabilities
from src.rulesets.legacy_adapter import LegacyRulesetAdapter
from . import character


class Coc7eRuntime(LegacyRulesetAdapter):
    runtime_id = 'core:coc7e'
    runtime_version = 1
    capabilities = RulesetCapabilities(experience_profile='coc7e', character_builder='professional',
        narrative_turns=True, versioned_state=True, authoritative_intents=True,
        deterministic_combat=True, adventure_formats=(ADVENTURE_GRAPH_FORMAT_V2,))

    def __init__(self):
        from src.engine.modules.legacy_combat import register_combat_projector
        register_combat_projector(self.runtime_id, self._combat_projection)

    @staticmethod
    def _combat_projection(instance: Any) -> dict:
        from .combat_runtime import state
        encounter = state(instance)
        active = bool(encounter and encounter.get('status') == 'active')
        order = encounter.get('order', []) if encounter else []
        current = encounter.get('current') if encounter else None
        return {'combat_active': active, 'combat_state': 'active' if active else 'none',
                'initiative_order': order if active else [],
                'initiative_current': order.index(current) if current in order else 0}

    def game_binding(self, rule: Any, locale: str) -> dict:
        return {'rule_id': rule.rule_id, 'runtime_id': self.runtime_id, 'runtime_version': 1,
                'content_version': '0.1', 'state_schema_version': 1}

    def on_player_join(self, instance: Any, user_id: str) -> None:
        from types import SimpleNamespace
        sheet = instance.get_character_sheet(user_id)
        canonical = sheet.get('ruleset_character', {})
        draft = canonical.get('draft')
        binding = canonical.get('rule_binding', {})
        if binding.get('runtime_id') != self.runtime_id or not instance.ruleset_binding_matches(binding):
            raise ValueError('Investigator binding does not match the game')
        # The generic seat factory initializes legacy resources and equipment.
        # Replace that projection from the same validated form, including Luck,
        # profile, age, MP and MOVE; never let d20 defaults replace the draft.
        sheet.update(character.finalize(SimpleNamespace(rule_id=binding['rule_id']), draft))

    def apply_narrative_sanity(self, instance: Any, uid: str, update: dict) -> None:
        from .sanity import apply_event
        apply_event(instance, uid, update)

    def apply_narrative_vitality(self, instance: Any, uid: str, update: dict) -> None:
        from .health import apply_injury
        apply_injury(instance, uid, update)

    def automatic_luck_decision(self, instance: Any, rule: Any, check: dict) -> bool | None:
        from src.engine.player_control import control_mode
        uid = str(check.get('actor_uid') or '')
        if uid not in instance.players or control_mode(instance, uid) != 'ai':
            return None
        # Conservative, deterministic default. SAN/Luck checks and fumbles cannot
        # become eligible by model request; the core resolver is still authority.
        cost = int(check.get('luck_cost') or 0)
        remaining = int(instance.get_character_sheet(uid).get('luck', 0))
        return 0 < cost <= 10 and remaining - cost >= 20

    def describe_experience(self, rule: Any, locale: str) -> dict:
        return {'profile': 'coc7e', 'rule_id': rule.rule_id, 'builder_mode': 'professional',
                'title': 'CoC 7e 调查员', 'status': 'development',
                'limitations': ['20–39岁及部分职业建卡', '基础战斗已接入；射击细则、战技、追逐和魔法自动化尚未完成']}

    def builder_choices(self, rule: Any, draft: dict) -> dict:
        return character.choices()

    def character_draft_prompt(self, rule: Any) -> str:
        return ('请根据用户要求填写CoC调查员表格，只返回JSON对象，不加代码围栏。'
                '必须满足给出的结构和合法范围，不编造骰点或资源。采用quick标准数组，'
                '年龄20–39，幸运15–90的5倍数。occupation_spends和interest_spends填投入点，'
                '不是最终技能值。信用评级仅用职业点购买。私家侦探职业点为'
                'EDU×2+max(STR,DEX)×2，其他已列职业EDU×4；兴趣点INT×2。'
                '不超过额度，不购买克苏鲁神话。保持团队忠诚。可参考合法示例并修改背景。'
                '表格定义及合法示例：\n' + json.dumps(character.choices(), ensure_ascii=False))

    def validate_character(self, rule: Any, draft: dict) -> list[str]:
        return character.validate(draft)

    def derive_character(self, rule: Any, draft: dict) -> dict:
        return character.finalize(rule, draft)

    def finalize_character(self, rule: Any, draft: dict) -> dict:
        return character.finalize(rule, draft)

    def normalize_character_submission(self, rule: Any, data: dict, locale: str = '') -> dict:
        canonical = data.get('ruleset_character')
        if not isinstance(canonical, dict) or canonical.get('schema_version') != 1:
            raise ValueError('CoC角色必须先通过调查员表格校验')
        expected = self.game_binding(rule, locale)
        if canonical.get('rule_binding') != expected:
            raise ValueError('CoC角色规则绑定不匹配')
        result = self.finalize_character(rule, canonical.get('draft', {}))
        for key in ('portrait',):
            if key in data:
                result[key] = deepcopy(data[key])
        from src.engine.player_control import preserve_creation_control
        return preserve_creation_control(data, result)

    def prepare_intent_submission(self, intent: dict, requester_id: str, requester_is_gm: bool) -> dict:
        allowed = {'type', 'actor_id', 'target_id', 'weapon_id', 'expected_revision',
                   'npc_ids', 'options', 'submitted_by', 'expected_run_id', 'mode', 'premise'}
        if set(intent) - allowed:
            raise ValueError('Unknown or privileged CoC intent fields')
        return {**intent, 'submitted_by': requester_id, '_requester_is_gm': requester_is_gm}

    def memory_deltas_from_event_batch(self, batch: dict, instance: Any) -> list:
        return []

    def available_intents(self, instance: Any, actor_id: str) -> list[dict]:
        from .combat_runtime import available
        return available(instance, actor_id, gm=actor_id == instance.gm_uid)

    def validate_intent(self, instance: Any, intent: dict) -> dict:
        from .combat_runtime import available
        if intent.get('type') == 'coc.combat.start':
            return {'ok': intent.get('_requester_is_gm') is True}
        choices = available(instance, str(intent.get('submitted_by') or ''), gm=bool(intent.get('_requester_is_gm')))
        return {'ok': any(all(intent.get(key) == value for key, value in choice.items()) for choice in choices)}

    def resolve_intent(self, instance: Any, intent: dict, rng: Any) -> dict:
        from .combat_runtime import resolve
        if intent.get('expected_run_id') != instance.run_id and not intent.get('_automatic'):
            return {'ok': False, 'code': 'STALE_RUN', 'error': '刷新当前对局后重试'}
        if intent.get('type') == 'coc.campaign.configure':
            from .campaign import resolve as configure
            try:
                return configure(instance, intent)
            except ValueError as exc:
                return {'ok': False, 'code': 'CAMPAIGN_REJECTED', 'error': str(exc)}
        return resolve(instance, intent, rng)

    def apply_event_batch(self, instance: Any, batch: dict) -> dict:
        if batch.get('domain') == 'campaign':
            from .campaign import apply as apply_campaign
            return apply_campaign(instance, batch)
        from .combat_runtime import apply
        return apply(instance, batch)

    def next_automatic_intent(self, instance: Any) -> dict | None:
        from .combat_runtime import automatic
        return automatic(instance)

    def hosted_intent_choices(self, instance: Any, seat_uid: str) -> list[dict]:
        from .combat_runtime import actor_choices
        from src.engine.player_control import control_mode
        if seat_uid not in instance.players or control_mode(instance, seat_uid) != 'ai':
            return []
        return [{**choice, '_automatic': True} for choice in actor_choices(instance, 'player:' + seat_uid)]

    def hosted_intent_context(self, instance: Any, seat_uid: str) -> dict:
        from .combat_runtime import view
        return view(instance, seat_uid)

    def gameplay_view(self, instance: Any, viewer_id: str = '', viewer_is_gm: bool = False) -> dict:
        from .combat_runtime import view
        from src.engine.modules import ruleset_runtime
        return {'combat': view(instance, viewer_id, viewer_is_gm), 'run_id': instance.run_id,
                'campaign': deepcopy(ruleset_runtime.state(instance).get('campaign', {})) if viewer_is_gm else {},
                'npcs': [{'id': key, 'name': row.get('name', key)} for key, row in instance.npcs.items()] if viewer_is_gm else []}

    def is_public_story_milestone(self, batch: dict) -> bool:
        return batch.get('runtime_id') == self.runtime_id and batch.get('domain') != 'campaign'

    def build_llm_view(self, instance: Any) -> dict:
        from .campaign import gm_context
        result = super().build_llm_view(instance)
        for uid, player in result.get('players', {}).items():
            sheet = player['character_sheet']
            source = instance.get_character_sheet(uid)
            # Percentile scores must not acquire the legacy d20 modifiers.
            # Compact skill rows so three full investigators fit the state budget.
            sheet.pop('_modifiers', None)
            sheet.pop('_armor', None)
            sheet['skills'] = {str(row.get('name') or row.get('id')): row.get('value')
                for row in source.get('skills', []) if isinstance(row, dict)}
            for key in ('sanity', 'luck', 'magic_points', 'move', 'damage_bonus', 'build',
                        'major_wound', 'unconscious', 'dying', 'madness', 'coc_sanity'):
                if key in source:
                    sheet[key] = deepcopy(source[key])
        return {'coc_keeper_contract': {
            'attribute_scale': 'percentile; no d20 modifiers',
            'past_plans': '历史讨论或决定不是永久禁令，以本轮已确认行动为准。',
            'progress': '核心线索遵守模组获取条件；成功须有实际结果，不能反复让玩家重新确认已知线索。'
                        '不要把每次失败都变成新的前置机关。同一失败尝试若无条件变化，应讨论改换方法或孤注一掷。',
            'time': '限时事件须按行动耗时推进并触发后果，不得无限重复逼近同一时刻。',
            'truth': '保持既定真相和已解决结果；不要将NPC猜测、过往提案或错误推论写成新的客观事实。',
        }, 'original_campaign': gm_context(instance), **result}

    def public_timeline_projection(self, batch: dict, locale: str) -> dict:
        actors = batch.get('combat', {}).get('actors', {})
        names = {key: row['name'] for key, row in actors.items()}
        intent = batch.get('intent', {})
        actor = names.get(intent.get('actor_id'), '守密人')
        text = [f"{actor}：{intent.get('type', '战斗行动')}"]
        for event in batch.get('events', []):
            kind = event.get('type')
            if kind == 'combat.damage':
                target = str(event.get('target_id') or '')
                hp = f"，HP {event.get('hp_before')}→{event.get('hp_after')}" if target.startswith('player:') else ''
                text.append(f"{names.get(target, '目标')}受到{event.get('damage', 0)}伤害{hp}。")
            elif kind == 'combat.reaction':
                text.append(f"{names.get(event.get('actor_id'), '防守者')}选择{event.get('mode')}，骰点{event.get('roll')}。")
            elif kind == 'combat.attack':
                text.append(f"攻击骰点{event.get('roll')}；成功等级{event.get('success_rank')}。")
        if batch.get('combat', {}).get('pending_reaction'):
            text.append('等待目标调查员选择防守反应，伤害尚未结算。')
        if batch.get('combat', {}).get('status') == 'ended':
            text.append('本次遭遇结束。')
        return {'action_text': text[0], 'gm_response': '\n'.join(text)}

