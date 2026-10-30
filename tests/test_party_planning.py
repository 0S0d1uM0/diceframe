"""Consent, isolation and persistence contracts of party deliberation."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.engine import party_planning as planning
from src.engine.game_instance import GameInstance, GameState
from src.engine.participant_view import Viewer
from src.engine.player_control import set_control
from src.webui.services.party_planning import PartyPlanningService, PlanningDependencies


def test_pure_json_uses_complete_response_instead_of_empty_narration():
    from src.commands.party_discussion import _object
    from src.llm.client import LLMClient
    response = LLMClient._to_response('{"confirmed":true}', 10, 'local')
    assert _object(response) == {'confirmed': True}


def fixture():
    instance = GameInstance(game_key=('web', 'planning', 'bot'), rule_id='coc7e')
    instance.state = GameState.ACTIVE_ACTION
    instance.gm_uid = 'host'
    for uid in ('human', 'ai'):
        instance.put_player(uid, {'user_id': uid, 'character_name': uid,
            'character_sheet': {'hp': 10, 'max_hp': 10, 'attributes': {'str': 50}}})
    set_control(instance, 'ai', 'ai')
    return instance


def body(instance, **extra):
    plan = planning.view(instance)
    return {'run_id': plan['run_id'], 'round': plan['round'], 'expected_revision': plan['revision'], **extra}


def propose_and_confirm(instance):
    planning.change(instance, 'propose', 'human', body(instance, text='我检查门锁'))
    planning.change(instance, 'propose', 'ai', body(instance, text='我在旁警戒'))
    for uid in ('human', 'ai'):
        planning.change(instance, 'confirm', uid, body(instance))


def service(instance, save=None, generate=None):
    async def persist(_):
        pass
    return PartyPlanningService(PlanningDependencies(lambda _: instance, save or persist,
        lambda _: SimpleNamespace(template={'party_planning': True}), generate))


def test_discussion_and_proposals_do_not_execute_actions_or_change_world():
    inst = fixture()
    world = deepcopy(inst.world_state)
    plan = planning.change(inst, 'message', 'human', body(inst, text='我们要不要先进屋？'))
    planning.change(inst, 'propose', 'human', body(inst, text='我准备检查门锁'))
    assert not inst.action_queue and not inst.ready_players
    assert inst.world_state == world and not plan['committed']


def test_new_opinion_revokes_all_consents_and_stale_confirmation_cannot_commit():
    inst = fixture()
    propose_and_confirm(inst)
    assert planning.ready(planning.view(inst))
    previous = body(inst)
    planning.change(inst, 'message', 'human', {**previous, 'text': '等一下，先别开门'})
    assert planning.view(inst)['confirmed'] == []
    with pytest.raises(ValueError):
        planning.commit(inst, previous)
    assert not inst.action_queue


def test_confirmed_plan_commits_exactly_one_action_per_investigator_and_roundtrips():
    inst = fixture()
    propose_and_confirm(inst)
    plan = planning.commit(inst, body(inst))
    assert plan['committed'] and len(inst.action_queue) == 2
    assert {row['user_id'] for row in inst.action_queue} == {'human', 'ai'}
    planning.commit(inst, body(inst))
    assert len(inst.action_queue) == 2
    restored = GameInstance.from_dict(inst.to_dict())
    assert planning.view(restored)['committed']
    assert len(restored.action_queue) == 2


def test_control_revision_roster_or_round_change_invalidates_plan():
    inst = fixture()
    propose_and_confirm(inst)
    set_control(inst, 'ai', 'human')
    assert not planning.ready(planning.view(inst))
    assert planning.view(inst)['proposals'] == {}


@pytest.mark.asyncio
async def test_save_failure_restores_plan_and_action_queue():
    inst = fixture()
    propose_and_confirm(inst)
    before = deepcopy(inst.to_dict())
    async def fail(_):
        raise OSError('disk full')
    result = await service(inst, fail).update('key', Viewer('gm', 'host'), 'commit', body(inst))
    assert not result['ok'] and inst.to_dict() == before


@pytest.mark.asyncio
async def test_loaded_paused_game_allows_discussion_and_resumes_only_at_confirmed_commit():
    inst = fixture(); inst.state = GameState.PAUSED
    result = await service(inst).update('key', Viewer('seat', 'human'), 'propose', body(inst, text='我检查门锁'))
    assert result['ok'] and inst.state == GameState.PAUSED and not inst.action_queue
    planning.change(inst, 'propose', 'ai', body(inst, text='我警戒'))
    for uid in ('human', 'ai'): planning.change(inst, 'confirm', uid, body(inst))
    result = await service(inst).update('key', Viewer('gm', 'host'), 'commit', body(inst))
    assert result['ok'] and inst.state == GameState.ACTIVE_ACTION and len(inst.action_queue) == 2


@pytest.mark.asyncio
async def test_human_cannot_confirm_for_an_ai_or_commit_on_behalf_of_party():
    inst = fixture()
    svc = service(inst)
    assert (await svc.update('key', Viewer('seat', 'human'), 'commit', body(inst)))['code'] == 'FORBIDDEN'
    assert (await svc.update('key', Viewer('gm', 'ai'), 'confirm', body(inst)))['code'] == 'FORBIDDEN'
    assert not svc.read('key', Viewer('outsider'))['ok']


@pytest.mark.asyncio
async def test_ai_proposes_and_reviews_but_never_confirms_for_human():
    inst = fixture()
    planning.change(inst, 'propose', 'human', body(inst, text='我检查门锁'))
    async def generate(_):
        return [{'uid': 'ai', 'text': '我照明并警戒', 'confirmed': True}]
    result = await service(inst, generate=generate).update('key', Viewer('gm', 'host'), 'generate', body(inst))
    assert result['ok'] and result['plan']['confirmed'] == ['ai']
    assert not planning.ready(result['plan']) and not inst.action_queue


@pytest.mark.asyncio
async def test_ai_objection_is_preserved_for_further_discussion_not_overridden():
    inst = fixture()
    async def generate(_):
        return [{'uid': 'ai', 'text': '我警戒', 'confirmed': False, 'review_reason': '分工重复，请先重新分配'}]
    result = await service(inst, generate=generate).update('key', Viewer('gm', 'host'), 'generate', body(inst))
    assert result['ok'] and result['plan']['reviews']['ai']['reason'] == '分工重复，请先重新分配'
    assert not result['plan']['confirmed'] and not inst.action_queue
    planning.change(inst, 'message', 'human', body(inst, text='我改去问路'))
    assert not planning.view(inst).get('reviews')


@pytest.mark.asyncio
async def test_ai_revises_after_objection_without_executing_or_confirming_for_human(monkeypatch):
    from src.commands.party_discussion import deliberate
    inst = fixture(); captured = []
    responses = iter([{'text': '我也检查门锁'}, {'confirmed': False, 'reason': '重复分工，请改为警戒'},
                      {'text': '我负责警戒'}, {'confirmed': True, 'reason': ''}])
    async def call(instance, uid, system, context, *args):
        captured.append(context)
        return next(responses)
    monkeypatch.setattr('src.commands.party_discussion._call', call)
    rows = await deliberate(inst, None)
    assert len(captured) == 4 and '重复分工，请改为警戒' in captured[2]
    assert rows[0]['text'] == '我负责警戒' and rows[0]['confirmed'] is True
    assert not inst.action_queue and not planning.view(inst)['confirmed']


@pytest.mark.asyncio
async def test_live_control_change_during_generation_discards_whole_model_plan():
    inst = fixture()
    async def generate(_):
        set_control(inst, 'ai', 'human')
        return [{'uid': 'ai', 'text': '我照明并警戒', 'confirmed': True}]
    result = await service(inst, generate=generate).update('key', Viewer('gm', 'host'), 'generate', body(inst))
    assert not result['ok'] and not planning.view(inst)['proposals']
    assert not inst.action_queue


@pytest.mark.asyncio
async def test_background_usage_and_summary_refresh_do_not_discard_or_get_overwritten():
    from src.engine.modules import narrative_notes, session_stats
    inst = fixture()
    async def generate(staged):
        session_stats.record_llm_usage(inst, 7, calls=1)
        narrative_notes.replace_summary(inst, {'narrative': '后台整理的公开摘要'})
        session_stats.record_llm_usage(staged, 11, calls=1)
        return [{'uid': 'ai', 'text': '我照明并警戒', 'confirmed': True}]
    result = await service(inst, generate=generate).update('key', Viewer('gm', 'host'), 'generate', body(inst))
    assert result['ok']
    assert session_stats.total_tokens(inst) == 18 and session_stats.total_llm_calls(inst) == 2
    assert narrative_notes.summary(inst)['narrative'] == '后台整理的公开摘要'

