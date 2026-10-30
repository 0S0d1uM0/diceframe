"""Party discussion never calls the Keeper or advances the game."""
from aiohttp import web
from src.webui.routes._common import _get_api
from src.webui.viewer import viewer_for


async def party_plan(request: web.Request) -> web.Response:
    api = _get_api(request)
    key = request.match_info['game_key']
    inst = api.get_game_instance(key)
    if inst is None:
        return web.json_response({'ok': False, 'code': 'GAME_NOT_FOUND'}, status=404)
    viewer = viewer_for(request, inst)
    if request.method == 'GET':
        result = api.party_plan(key, viewer)
    else:
        if request.get('bot_surface') == 'read_only' or (request.get('player_preview') and not request.get('player_delegate')):
            return web.json_response({'ok': False, 'code': 'FORBIDDEN'}, status=403)
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({'ok': False, 'code': 'INVALID_REQUEST'}, status=400)
        result = await api.update_party_plan(key, viewer, request.match_info['operation'], body)
        if result.get('ok') and request.app.get('connection_pool') is not None:
            await request.app['connection_pool'].broadcast(key, {'type': 'party_plan_changed'})
    return web.json_response(result, status=200 if result.get('ok') else 403 if result.get('code') == 'FORBIDDEN' else 409)


def register_party_planning(app: web.Application) -> None:
    app.router.add_get('/api/games/{game_key}/party-plan', party_plan)
    app.router.add_post('/api/games/{game_key}/party-plan/{operation:message|propose|confirm|generate|commit}', party_plan)
