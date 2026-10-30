from types import SimpleNamespace
import pytest
from src.engine.game_instance import GameInstance
from src.engine.modules import narrative_notes
from src.memory.summarizer import build_summary_input, summarize


def fixture():
    inst = GameInstance(game_key=('web', 'summary-continuity', 'bot'))
    inst.put_player('a', {'user_id': 'a', 'character_name': '林照', 'character_sheet': {'hp': 10}})
    narrative_notes.replace_summary(inst, {'narrative': '早期调查的摘要'})
    narrative_notes.replace_key_facts(inst, [{'type': 'clue', 'content': '第2轮获得的铜片线索'}])
    inst.log = [{'round': 11, 'actions': [{'user_id': 'a', 'text': '我检查门'}], 'gm_response': '门没有上锁。'}]
    return inst


@pytest.mark.asyncio
async def test_rolling_summary_receives_old_facts_as_well_as_narrative_and_speakers():
    inst = fixture(); calls = []
    async def call(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content='{"narrative":"新摘要","key_facts":[{"type":"clue","content":"铜片线索仍未解决"}]}', narration='')
    await summarize(inst, SimpleNamespace(call=call), 'summary system')
    assert '第2轮获得的铜片线索' in calls[0]['user_message']
    assert '林照: 我检查门' in calls[0]['user_message']
    assert '暂时计划不能当成永久限制' in calls[0]['system_prompt']
    assert narrative_notes.key_facts(inst)[0]['content'] == '铜片线索仍未解决'


@pytest.mark.asyncio
async def test_malformed_summary_does_not_erase_earlier_durable_facts():
    inst = fixture()
    async def call(**kwargs):
        return SimpleNamespace(content='plain prose rather than JSON', narration='摘要格式失败')
    await summarize(inst, SimpleNamespace(call=call), 'summary system')
    assert narrative_notes.key_facts(inst)[0]['content'] == '第2轮获得的铜片线索'
    assert '林照: 我检查门' in build_summary_input(inst)
