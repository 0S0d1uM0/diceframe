"""Explicit regular/endless original-game intent, without rewriting world truth."""
from copy import deepcopy
from uuid import uuid4
from src.engine.modules import ruleset_runtime, run_story


def resolve(instance, intent):
    if not intent.get('_requester_is_gm') or instance.adventure_binding:
        raise ValueError('Only the Keeper may configure an unbound original game')
    if instance.action_queue or any(row.get('actions') for row in instance.log):
        raise ValueError('Choose the original-game mode before the first committed action')
    mode, premise = intent.get('mode'), intent.get('premise', '')
    if mode not in ('regular', 'endless') or not isinstance(premise, str) or len(premise) > 2000:
        raise ValueError('Choose regular/endless and a premise of at most 2000 characters')
    current = ruleset_runtime.state(instance).get('campaign', {})
    revision = current.get('revision', 0)
    if type(intent.get('expected_revision')) is not int or intent['expected_revision'] != revision:
        raise ValueError('Campaign configuration changed')
    if mode == 'endless' and run_story.snapshot(instance).get('plan'):
        raise ValueError('An adopted outline already exists; use a fresh original game for endless mode')
    return {'ok': True, 'event_batch': {'batch_id': uuid4().hex, 'runtime_id': 'core:coc7e',
        'domain': 'campaign', 'run_id': instance.run_id, 'expected_revision': revision,
        'campaign': {'mode': mode, 'premise': premise.strip(), 'revision': revision + 1}, 'events': []}}


def apply(instance, batch):
    ruleset_runtime.require_binding(instance, 'core:coc7e')
    if batch.get('run_id') != instance.run_id or batch.get('runtime_id') != 'core:coc7e':
        raise ValueError('Campaign batch belongs to another run')
    state = ruleset_runtime.state(instance)
    current = state.get('campaign', {})
    if current.get('revision', 0) != batch.get('expected_revision'):
        raise ValueError('Campaign changed before publication')
    state['campaign'] = deepcopy(batch['campaign'])
    return {'applied': True, 'batch_id': batch['batch_id']}


def gm_context(instance):
    value = deepcopy(ruleset_runtime.state(instance).get('campaign', {}))
    if value.get('mode') == 'endless':
        value['keeper_guidance'] = ('无尽原创团：没有预设总终局或固定大纲。当前事件可以结束，'
            '但后续事件从已有事实、NPC动机和玩家选择自然生长。保留已解决问题的结果，'
            '不要通过不断推翻真相、复活敌人或无限制造同一危机强行续写。玩家可随时选择收团。')
    elif value.get('mode') == 'regular':
        value['keeper_guidance'] = '常规原创团：依据开局采用的大纲主持，允许偏离路线，保留核心真相与结束条件。'
    return value
