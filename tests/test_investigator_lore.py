from types import SimpleNamespace
import pytest
from src.commands.player_knowledge import retrieve_player_lore


@pytest.mark.asyncio
async def test_hosted_lore_requires_both_character_projection_and_explicit_visibility():
    inst = SimpleNamespace(players={'p': {'character_name': '林照'}})
    rows = [{'id': 'public', 'visible_to': ['all']},
            {'id': 'secret', 'visible_to': []},
            {'id': 'guessed', 'visible_to': ['p']}]
    calls = []
    async def retrieve(*args, **kwargs):
        calls.append(kwargs)
        return rows
    projection = SimpleNamespace(for_character=lambda *args, **kwargs: rows[:2])
    result = await retrieve_player_lore(inst, 'p', '猜测关键词', retriever=SimpleNamespace(retrieve=retrieve), projection=projection)
    assert [row['id'] for row in result] == ['public']
    assert calls[0]['viewer_is_gm'] is False and calls[0]['mutate_timers'] is False
    assert calls[0]['action_actor_uids'] == ['p']


@pytest.mark.asyncio
async def test_missing_player_projection_never_falls_back_to_keeper_lore():
    inst = SimpleNamespace(players={'p': {}})
    async def forbidden(*args, **kwargs):
        pytest.fail('No retrieval without an authorized character projection')
    assert await retrieve_player_lore(inst, 'p', 'truth', retriever=SimpleNamespace(retrieve=forbidden), projection=None) == []
