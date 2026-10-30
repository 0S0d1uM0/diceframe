"""Two-pass AI party discussion using character-safe contexts, never GM state."""
from __future__ import annotations
import json
from typing import Any

from src.engine import party_planning
from src.engine.player_control import control_mode
from src.llm.context_builder import build_player_safe_context


def _object(response: Any) -> dict:
    text = str(getattr(response, 'content', '') or getattr(response, 'narration', '') or '').strip()
    if text.startswith('```'):
        text = '\n'.join(text.splitlines()[1:-1])
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Discussion response must be an object')
    return value


async def deliberate(instance: Any, llm_client: Any, seat_runtime: Any = None, player_lore: Any = None) -> list[dict]:
    """Negotiate on an isolated planning aggregate, with at most three passes."""
    result = []
    for _ in range(3):
        result = await _deliberate_pass(instance, llm_client, seat_runtime, player_lore)
        if not result or all(row['confirmed'] for row in result):
            return result
        # Retain explicit objections for the next pass. No action is submitted,
        # no human proposal is changed and nobody's consent is manufactured.
        plan = party_planning.view(instance)
        for row in result:
            plan['proposals'][row['uid']] = {key: row[key] for key in
                ('text', 'selected_skill', 'selected_attribute', 'target_text')}
        plan['confirmed'] = []
        plan['reviews'] = {row['uid']: {'confirmed': row['confirmed'], 'reason': row['review_reason']} for row in result}
        party_planning.store(instance, plan)
    return result


async def _deliberate_pass(instance: Any, llm_client: Any, seat_runtime: Any = None, player_lore: Any = None) -> list[dict]:
    plan = party_planning.view(instance)
    uids = [uid for uid in plan['roster'] if control_mode(instance, uid) == 'ai']
    result = []
    for uid in uids:
        identity = f"你的角色是{instance.players[uid].get('character_name', uid)}，提案中的用户ID是{uid}。"
        system = (
            '你扮演一位CoC调查员，与同伴商量计划，尚未向KP提交行动。你完全忠于团队，'
            '不背叛、不偷窃、不替同伴作主、不把猜测当事实、不叙述行动结果。保持角色性格，'
            '听取队友意见，避免重复分工。只返回JSON对象：'
            '{"text":"第一人称拟采取的一项行动，1至3句", "selected_skill":"可选技能名或空字符串",'
            '"selected_attribute":"可选属性ID或空字符串","target_text":"目标名称或空字符串"}。'
            '任何骰点、结果、伤害、检定难度由服务端和KP裁定。'
            '仅在需要且合理时填写技能；普通询问、走过已获准进入的门等不必强行指定技能。'
            '不得凭空使用角色卡没有列出、现场也未明确存在的相机、武器、手电或其他工具。'
            '谨慎不等于无限拖延：若上一轮没得到信息，应换调查渠道、接近方式或风险控制，'
            '不要反复提出相同失败尝试，也不必查清全部未知才迈出合理的下一步。'
            '过去某轮“暂不进入”“先观察”等临时计划只适用于当轮，不是永久禁令。'
            '当新线索降低风险或原方案没有进展时，可以重新提出改变分工或进入下一处地点，'
            '由本轮全员重新确认。关注已接受的调查目标和受困者，不要把取得绝对安全当作行动前提。'
        )
        system += identity + ('已有队友正在做的事不必再提一遍；选择互补分工，或明确说明你怎样协助。'
            '若有上一轮审核意见，针对其中的具体异议修改自己的分工；不要只重复被否决的原提案。')
        lore = await player_lore(instance, uid, '当前场景与队内调查计划') if player_lore is not None else []
        context = await build_player_safe_context(instance, system, lore,
            '仅提出计划，不执行。当前讨论和提案：\n' + json.dumps({
                'messages': plan['messages'], 'proposals': plan['proposals'],
                'previous_reviews': plan.get('reviews', {})}, ensure_ascii=False), uid)
        row = await _call(instance, uid, system, context, llm_client, seat_runtime, 1536)
        if not isinstance(row.get('text'), str) or not 1 <= len(row['text'].strip()) <= 2000:
            raise ValueError('Invalid investigator proposal')
        proposal = {key: row.get(key, '') for key in ('text', 'selected_skill', 'selected_attribute', 'target_text')}
        if any(not isinstance(value, str) for value in proposal.values()):
            raise ValueError('Invalid action fields')
        plan['proposals'][uid] = proposal
        result.append({'uid': uid, **proposal, 'confirmed': False})
    # Every AI reviews exactly the same final proposed plan, after all proposals.
    for row in result:
        uid = row['uid']
        system = ('你是忠于团队的CoC调查员。现在审核全队的拟行动，不执行任何行动。'
                  '检查是否分工冲突、是否遗漏队友的明确异议。只代表自己确认。'
                  '接受当前提案返回JSON {"confirmed":true,"reason":""}，否则返回 {"confirmed":false,"reason":"具体异议和建议"}。'
                  '不得假装人类已经同意。你的确认不代表任何同伴的确认。')
        system += ('仅本轮明确异议需要处理。每人的本轮新提案可以替代其过去的临时计划或前提，'
                   '过去轮次“暂不进入”“必须有人监听”等不是永久命令。可以指出新方案实际风险，'
                   '但不能仅因它改变旧分工就否决。不要要求调查开始前证明绝对安全。')
        system += f"你的角色是{instance.players[uid].get('character_name', uid)}，你的提案ID是{uid}。"
        lore = await player_lore(instance, uid, '当前场景与队内调查计划') if player_lore is not None else []
        context = await build_player_safe_context(instance, system, lore,
            '待审核计划：\n' + json.dumps({'messages': plan['messages'], 'proposals': plan['proposals']}, ensure_ascii=False), uid)
        review = await _call(instance, uid, system, context, llm_client, seat_runtime, 1024)
        row['confirmed'] = review.get('confirmed') is True
        row['review_reason'] = str(review.get('reason') or '')[:1000]
    return result


async def _call(instance: Any, uid: str, system: str, context: str, client: Any, seats: Any, max_tokens: int) -> dict:
    generation = seats.begin(instance, uid) if seats is not None else None
    outcome = {'status': 'discarded', 'reason': 'discussion_failed'}
    try:
        selected = generation.client if generation is not None else client
        if selected is None:
            raise ValueError('Investigator model not configured')
        if generation is not None and generation.admission_check():
            raise ValueError('AI configuration changed')
        style = generation.style_prompt if generation is not None else ''
        response = await selected.call(system + '\n' + style, context, max_tokens=max_tokens, temperature=0.5)
        if generation is not None and generation.admission_check():
            raise ValueError('AI configuration changed')
        instance.record_llm_usage(int(getattr(response, 'total_tokens', 0) or 0), calls=1)
        result = _object(response)
        outcome = {'status': 'added', 'reason': ''}
        return result
    finally:
        if generation is not None:
            generation.finish(outcome)
            await generation.close()

