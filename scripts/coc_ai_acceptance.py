"""Repeatable local HTTP acceptance. Run after DSH local has stopped.

Examples: python scripts/coc_ai_acceptance.py create
          python scripts/coc_ai_acceptance.py play --rounds 3
          python scripts/coc_ai_acceptance.py create --human
Runtime credentials and evidence stay under ignored data/coc_acceptance/.
"""
from __future__ import annotations
import argparse
import http.cookiejar
import json
import re
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(ROOT))
from src.rulesets.coc7e.character import example_draft


class Client:
    def __init__(self, human: bool, case: str = ''):
        if case and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', case):
            raise ValueError('Case must contain only letters, digits, underscore or hyphen')
        self.directory = ROOT / 'data' / 'coc_acceptance' / (('human' if human else 'ai') + ('-' + case if case else ''))
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_file = self.directory / 'session.json'
        self.state = json.loads(self.state_file.read_text(encoding='utf-8')) if self.state_file.exists() else {}
        self.cookies = http.cookiejar.LWPCookieJar(str(self.directory / 'cookies.txt'))
        if Path(self.cookies.filename).exists():
            self.cookies.load(ignore_discard=True)
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.password = (ROOT / 'data' / 'access_token.txt').read_text(encoding='utf-8').strip()

    def call(self, method: str, path: str, body=None, *, required=True):
        request = urllib.request.Request('http://127.0.0.1:18000/api' + path,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), method=method,
            headers={'Authorization': 'Bearer ' + self.password, 'Content-Type': 'application/json', 'X-TRPG-Confirm': 'true'})
        try:
            with self.opener.open(request, timeout=900) as response:
                status = response.status
                data = json.load(response)
        except urllib.error.HTTPError as error:
            status = error.code
            data = json.load(error)
        self.cookies.save(ignore_discard=True)
        record = {'method': method, 'path': path, 'status': status, 'response': redact(data)}
        with (self.directory / 'http.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        if required and (status >= 400 or data.get('ok') is False):
            raise RuntimeError(f'{method} {path}: {status}: {data.get("error") or data.get("code") or data.get("error_code")}')
        return data

    @property
    def game(self):
        return '/games/' + urllib.parse.quote(self.state['game_key'], safe='')

    def save(self):
        self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')

    def generate_finale(self, body):
        request = urllib.request.Request('http://127.0.0.1:18000/api' + self.game + '/run-story/generate/finale',
            data=json.dumps(body).encode(), method='POST', headers={'Authorization': 'Bearer ' + self.password,
            'Content-Type': 'application/json', 'X-TRPG-Confirm': 'true'})
        result = None
        with self.opener.open(request, timeout=900) as response:
            for line in response:
                event = json.loads(line)
                if event.get('type') == 'error': raise RuntimeError(event.get('error'))
                if event.get('type') == 'progress': print(json.dumps(event, ensure_ascii=False), flush=True)
                if event.get('type') == 'result': result = event
        if not result or not result.get('ok'):
            raise RuntimeError('No usable finale draft; preparation retained')
        self.cookies.save(ignore_discard=True)
        return result


def redact(value):
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: '[redacted]' if any(secret in key for secret in ('token', 'password', 'credential', 'api_key')) else redact(item)
                for key, item in value.items()}
    return value


def scope(plan):
    return {'run_id': plan['run_id'], 'round': plan['round'], 'expected_revision': plan['revision']}


def create(client: Client, human: bool):
    client.call('POST', '/login', {'password': client.password})
    players = []
    for index, (name, personality) in enumerate([
        ('林照', '谨慎的私家侦探，倾向查看现场痕迹，愿意听取同伴意见，忠于团队。'),
        ('周衡', '沉着的调查搭档，关注声音、工具和维修细节，不抢同伴分工，忠于团队。'),
        ('沈棠', '善于沟通且关心受困者，愿意与委托人交谈并记录线索，忠于团队。'),
    ]):
        draft = example_draft()
        draft['name'] = name
        draft['profile'] = {'personality': personality, 'backstory': '三位相识多年的调查搭档，相互信任，共同接受玛拉的寻人委托。'}
        result = client.call('POST', '/rules/coc7e/builder/finalize', draft)
        card = result['character']
        card['control'] = 'human' if human and index == 0 else 'ai'
        players.append(card)
    result = client.call('POST', '/games/create', {'world_id': 'coc_clockwork', 'rule_id': 'coc7e',
        'game_name': '雨夜钟表铺 · ' + ('真人验收' if human else '全AI验收'),
        'solo': False, 'language': 'zh-CN', 'difficulty': '标准', 'room_password': '', 'players': players})
    client.state['game_key'] = result['game_key']
    client.state['players'] = [{'name': p.get('character_name'), 'uid': p.get('user_id')} for p in result.get('players', [])]
    client.save()
    client.call('POST', client.game + '/claim-gm', {})
    print(json.dumps({'created': client.state['game_key'], 'mode': 'human+2ai' if human else '3ai'}, ensure_ascii=False), flush=True)


def play(client: Client, rounds: int):
    for _ in range(rounds):
        plan = client.call('GET', client.game + '/party-plan')['plan']
        if any(row['mode'] != 'ai' for row in plan['roster'].values()):
            raise RuntimeError('Automated acceptance cannot confirm a human-controlled seat')
        before = client.call('GET', client.game + '/log')
        generated = client.call('POST', client.game + '/party-plan/generate', scope(plan))
        after = client.call('GET', client.game + '/log')
        if before != after:
            raise RuntimeError('Discussion unexpectedly changed the settled game log')
        plan = generated['plan']
        print(json.dumps({'round': plan['round'], 'proposals': plan['proposals'], 'confirmed': plan['confirmed']}, ensure_ascii=False), flush=True)
        if set(plan['confirmed']) != set(plan['roster']):
            raise RuntimeError('An AI investigator withheld consent; inspect the proposed plan')
        client.call('POST', client.game + '/party-plan/commit', scope(plan))
        result = client.call('POST', client.game + '/advance', {'force': False})
        if result.get('phase') == 'luck':
            raise RuntimeError('All-AI run still requires a post-check decision')
        print(json.dumps({'round': plan['round'], 'phase': result.get('phase'),
            'narration': result.get('narration', ''), 'check_results': result.get('check_results', [])}, ensure_ascii=False), flush=True)
        current = client.call('GET', client.game + '/party-plan')['plan']
        if current['round'] <= plan['round']:
            raise RuntimeError('Keeper did not complete the confirmed round')
    client.call('GET', client.game)
    client.call('GET', client.game + '/characters')
    print('Acceptance rounds completed; evidence: ' + str(client.directory), flush=True)


def finale(client: Client, commit: bool):
    """Explicit reviewer commands: never infer story completion from round count."""
    if any(row['mode'] != 'ai' for row in client.call('GET', client.game + '/party-plan')['plan']['roster'].values()):
        raise RuntimeError('This acceptance command cannot finalize human play')
    story = client.call('GET', client.game + '/run-story')
    if commit:
        draft = json.loads((client.directory / 'finale-draft.json').read_text(encoding='utf-8'))['draft']
        job = story['finale']
        if draft['job_id'] != job['id'] or draft['run_id'] != story['run_id']:
            raise RuntimeError('Draft belongs to another finale')
        saved = client.call('POST', client.game + '/run-story/materials', {
            'run_id': story['run_id'], 'job_id': job['id'], 'job_revision': job['revision'],
            'epilogue': draft['epilogue'], 'recap': draft['recap'], 'gm_notes': 'Local-model all-AI acceptance; public outcomes reviewed before settlement.'})
        ended = client.call('POST', client.game + '/run-story/commit', {'run_id': story['run_id'],
            'job_id': job['id'], 'job_revision': saved['finale']['revision'], 'confirmed': True})
        assert ended['finale']['status'] == 'ended'
        print('Reviewed finale archived: ' + job['id'], flush=True)
    else:
        prepared = client.call('POST', client.game + '/run-story/prepare', {'run_id': story['run_id']})
        result = client.generate_finale({'run_id': story['run_id'], 'job_id': prepared['finale']['id'], 'token_consent': True})
        (client.directory / 'finale-draft.json').write_text(json.dumps(redact(result), ensure_ascii=False, indent=2), encoding='utf-8')
        print('Finale draft saved for review; it has not been committed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('create', 'play', 'finale-draft', 'finale-commit'))
    parser.add_argument('--human', action='store_true')
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--case', default='', help='Separate evidence/session directory for a regression run')
    args = parser.parse_args()
    client = Client(args.human, args.case)
    if args.command == 'create': create(client, args.human)
    elif args.command == 'play': play(client, max(1, min(20, args.rounds)))
    else: finale(client, args.command == 'finale-commit')
