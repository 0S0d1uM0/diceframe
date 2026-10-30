"""Authorized, non-mutating lore retrieval shared by hosted investigators."""
from typing import Any
from src.llm.context_builder import filter_player_visible_lorebook_entries


async def retrieve_player_lore(instance: Any, uid: str, query: str, *, retriever: Any, projection: Any) -> list[dict]:
    if retriever is None or projection is None or uid not in instance.players:
        return []  # Never substitute GM knowledge when the player projection is absent.
    name = str(instance.players[uid].get('character_name') or uid)
    matches = await retriever.retrieve(instance, query, viewer_is_gm=False,
        viewer_uid=uid, viewer_name=name, mutate_timers=False, action_actor_uids=[uid])
    allowed = {str(row.get('id') or '') for row in projection.for_character(instance, uid, viewer_name=name)} - {''}
    return [row for row in filter_player_visible_lorebook_entries(matches, uid, name)
            if str(row.get('id') or '') in allowed]
