"""One validated investigator form for humans, model drafts and imports."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ATTRIBUTES = ('str', 'con', 'siz', 'dex', 'app', 'int', 'pow', 'edu')
STANDARD_ARRAY = (40, 50, 50, 50, 60, 60, 70, 80)
# Stable IDs own mechanics; labels are presentation only.
SKILLS = {
    'spot_hidden': ('侦查', 25), 'listen': ('聆听', 20), 'library_use': ('图书馆使用', 20),
    'psychology': ('心理学', 10), 'fast_talk': ('话术', 5), 'persuade': ('说服', 10),
    'intimidate': ('恐吓', 15), 'charm': ('魅惑', 15), 'stealth': ('潜行', 20),
    'track': ('追踪', 10), 'first_aid': ('急救', 30), 'medicine': ('医学', 1),
    'psychoanalysis': ('精神分析', 1), 'occult': ('神秘学', 5), 'cthulhu_mythos': ('克苏鲁神话', 0),
    'history': ('历史', 5), 'natural_world': ('博物学', 10), 'anthropology': ('人类学', 1),
    'archaeology': ('考古学', 1), 'accounting': ('会计', 5), 'law': ('法律', 5),
    'foreign_language': ('外语', 1), 'own_language': ('母语', 0), 'fighting_brawl': ('格斗（斗殴）', 25),
    'dodge': ('闪避', 0), 'firearms_handgun': ('射击（手枪）', 20),
    'firearms_rifle': ('射击（步枪／霰弹枪）', 25), 'throw': ('投掷', 20),
    'drive': ('汽车驾驶', 20), 'mechanical_repair': ('机械维修', 10),
    'electrical_repair': ('电气维修', 10), 'locksmith': ('锁匠', 1),
    'survival': ('生存', 10), 'credit_rating': ('信用评级', 0),
    'photography': ('艺术／手艺（摄影）', 5), 'appraise': ('估价', 5),
}
# Each occupation owns its point formula, separate from display labels.
OCCUPATIONS = {
    'private_detective': {'name': '私家侦探', 'credit': (9, 30), 'skills': ('spot_hidden', 'psychology', 'fast_talk', 'law', 'library_use', 'photography', 'locksmith', 'track')},
    'scholar': {'name': '学者', 'credit': (20, 70), 'skills': ('library_use', 'history', 'foreign_language', 'own_language', 'occult', 'archaeology', 'anthropology', 'persuade')},
    'doctor': {'name': '医生', 'credit': (30, 80), 'skills': ('first_aid', 'medicine', 'psychology', 'psychoanalysis', 'foreign_language', 'library_use', 'persuade', 'natural_world')},
    'journalist': {'name': '记者', 'credit': (9, 30), 'skills': ('spot_hidden', 'listen', 'fast_talk', 'persuade', 'psychology', 'library_use', 'photography', 'foreign_language')},
}


def choices() -> dict:
    return {'attributes': list(ATTRIBUTES), 'standard_array': list(STANDARD_ARRAY),
            'occupations': [{'id': key, **value} for key, value in OCCUPATIONS.items()],
            'skills': [{'id': key, 'name': label, 'base': base} for key, (label, base) in SKILLS.items()],
            'schema_version': 1, 'methods': ['quick', 'manual'],
            'draft_example': example_draft()}


def example_draft() -> dict:
    return {'schema_version': 1, 'name': '调查员', 'age': 28, 'method': 'quick',
            'occupation': 'private_detective', 'luck': 50,
            'attributes': dict(zip(ATTRIBUTES, (50, 50, 50, 60, 40, 70, 60, 80))),
            'occupation_spends': {'credit_rating': 10, 'spot_hidden': 35, 'psychology': 35,
                                  'library_use': 35, 'fast_talk': 35, 'locksmith': 35,
                                  'law': 35, 'track': 35, 'photography': 25},
            'interest_spends': {'first_aid': 30, 'listen': 30, 'stealth': 30, 'fighting_brawl': 30},
            'profile': {'personality': '谨慎、忠于团队，愿意讨论分工', 'backstory': ''}}


def base_values(attributes: dict) -> dict[str, int]:
    result = {key: base for key, (_, base) in SKILLS.items()}
    result['own_language'] = attributes['edu']
    result['dodge'] = attributes['dex'] // 2
    return result


def occupation_points(occupation: str, attributes: dict) -> int:
    if occupation == 'private_detective':
        return 2 * (attributes['edu'] + max(attributes['str'], attributes['dex']))
    return attributes['edu'] * 4


def validate(draft: Any) -> list[str]:
    if not isinstance(draft, dict):
        return ['角色表必须是对象']
    errors = []
    if type(draft.get('schema_version')) is not int or draft['schema_version'] != 1:
        errors.append('不支持的角色表版本')
    if not isinstance(draft.get('name'), str) or not 1 <= len(draft['name'].strip()) <= 120:
        errors.append('姓名长度须为1–120字')
    if type(draft.get('age')) is not int or not 20 <= draft['age'] <= 39:
        errors.append('当前建卡器支持20–39岁；其他年龄的规则调整尚未接入')
    if type(draft.get('luck')) is not int or draft['luck'] not in range(15, 91, 5):
        errors.append('初始幸运须为15–90之间的5的倍数（3d6×5）')
    occupation = OCCUPATIONS.get(draft.get('occupation')) if isinstance(draft.get('occupation'), str) else None
    if occupation is None:
        errors.append('请选择受支持的职业')
    attributes = draft.get('attributes')
    if not isinstance(attributes, dict) or set(attributes) != set(ATTRIBUTES):
        errors.append('必须填写完整的八项属性')
        attributes = {}
    else:
        for key in ATTRIBUTES:
            floor = 40 if key in ('siz', 'int', 'edu') else 15
            if type(attributes[key]) is not int or not floor <= attributes[key] <= 90:
                errors.append(f'{key} 超出初始属性范围')
    method = draft.get('method')
    if method not in ('quick', 'manual'):
        errors.append('请选择快速分配或手动录入属性')
    if method == 'quick' and attributes and all(type(v) is int for v in attributes.values()):
        if sorted(attributes.values()) != list(STANDARD_ARRAY):
            errors.append('快速分配须使用40、50、50、50、60、60、70、80，各一次')
    profile = draft.get('profile', {})
    if not isinstance(profile, dict) or any(not isinstance(v, str) or len(v) > 5000 for v in profile.values()):
        errors.append('背景字段必须是长度不超过5000的文本')
    allocations = []
    for field in ('occupation_spends', 'interest_spends'):
        allocation = draft.get(field, {})
        if (not isinstance(allocation, dict) or any(k not in SKILLS or k == 'cthulhu_mythos'
                or type(v) is not int or v < 0 or v > 99 for k, v in allocation.items())):
            errors.append(f'{field} 必须是合法技能的非负投入点数，不能购买克苏鲁神话')
            allocation = {}
        allocations.append(allocation)
    if not errors:
        job, interests = allocations
        assert occupation is not None
        if set(job) - set(occupation['skills']) - {'credit_rating'}:
            errors.append('职业点只能分配给所选职业技能及信用评级')
        if sum(job.values()) > occupation_points(draft['occupation'], attributes):
            errors.append('职业点超出所选职业的属性公式额度')
        if 'credit_rating' in interests:
            errors.append('个人兴趣点不能购买信用评级')
        if sum(interests.values()) > attributes['int'] * 2:
            errors.append('兴趣点超出INT×2')
        bases = base_values(attributes)
        values = {key: bases[key] + job.get(key, 0) + interests.get(key, 0) for key in SKILLS}
        if any(v > 99 for v in values.values()):
            errors.append('技能值不能超过99')
        low, high = occupation['credit']
        if not low <= values['credit_rating'] <= high:
            errors.append(f'本职业信用评级须为{low}–{high}')
    return errors


def finalize(rule: Any, draft: dict) -> dict:
    errors = validate(draft)
    if errors:
        raise ValueError('; '.join(errors))
    from .mechanics import damage_bonus, movement
    attrs = dict(draft['attributes'])
    skills = base_values(attrs)
    for field in ('occupation_spends', 'interest_spends'):
        for key, value in draft.get(field, {}).items():
            skills[key] += value
    hp = (attrs['con'] + attrs['siz']) // 10
    db = damage_bonus(attrs['str'], attrs['siz'])
    binding = {'rule_id': rule.rule_id, 'runtime_id': 'core:coc7e', 'runtime_version': 1,
               'content_version': '0.1', 'state_schema_version': 1}
    return {'name': draft['name'].strip(), 'character_name': draft['name'].strip(), 'rule_binding': deepcopy(binding),
            'rule_id': rule.rule_id, 'class': draft['occupation'], 'level': 1,
            'attributes': attrs, 'hp': hp, 'max_hp': hp, 'sanity': attrs['pow'],
            'max_sanity': 99, 'luck': draft['luck'], 'magic_points': attrs['pow'] // 5,
            'max_magic_points': attrs['pow'] // 5, 'move': movement(attrs['str'], attrs['dex'], attrs['siz'], draft['age']),
            'damage_bonus': db['formula'], 'build': db['build'], 'age': draft['age'],
            'skills': [{'id': key, 'name': SKILLS[key][0], 'value': value} for key, value in skills.items()],
            'profile': deepcopy(draft.get('profile', {})), 'background': draft.get('profile', {}).get('backstory', ''),
            'equipment': [], 'inventory': [], 'key_items': [], 'deceased': False,
            'ruleset_character': {'schema_version': 1, 'draft': deepcopy(draft),
                'rule_binding': binding}}

