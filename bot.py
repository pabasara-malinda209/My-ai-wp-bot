import os, time, json, base64, requests

TG = os.environ['TELEGRAM_BOT_TOKEN']
GEM = os.environ['GEMINI_API_KEY']
GH = os.environ['GH_PAT']
ALLOWED = os.environ.get('ALLOWED_CHAT_ID', '').strip()
MODEL = 'gemini-3.8-flash'
GHH = {'Authorization': 'Bearer ' + GH, 'Accept': 'application/vnd.github+json'}
API = 'https://api.github.com'


def tg(method, **p):
    return requests.post(f'https://api.telegram.org/bot{TG}/{method}', json=p, timeout=70).json()


def say(chat, text):
    for i in range(0, len(text) or 1, 3800):
        tg('sendMessage', chat_id=chat, text=text[i:i + 3800] or '.')


def t_list_repos():
    r = requests.get(f'{API}/user/repos?per_page=100', headers=GHH).json()
    return [x['full_name'] for x in r]


def t_list_files(repo, path=''):
    r = requests.get(f'{API}/repos/{repo}/contents/{path}', headers=GHH).json()
    return [x['path'] for x in r] if isinstance(r, list) else r


def t_read_file(repo, path):
    r = requests.get(f'{API}/repos/{repo}/contents/{path}', headers=GHH).json()
    if 'content' not in r:
        return r
    return base64.b64decode(r['content']).decode('utf-8', 'replace')[:20000]


def t_propose_change(repo, path, content, message):
    info = requests.get(f'{API}/repos/{repo}', headers=GHH).json()
    base = info['default_branch']
    sha = requests.get(f'{API}/repos/{repo}/git/ref/heads/{base}', headers=GHH).json()['object']['sha']
    branch = 'ai-bot/' + str(int(time.time()))
    requests.post(f'{API}/repos/{repo}/git/refs', headers=GHH, json={'ref': 'refs/heads/' + branch, 'sha': sha})
    cur = requests.get(f'{API}/repos/{repo}/contents/{path}?ref={branch}', headers=GHH).json()
    body = {'message': message, 'branch': branch, 'content': base64.b64encode(content.encode()).decode()}
    if isinstance(cur, dict) and 'sha' in cur:
        body['sha'] = cur['sha']
    requests.put(f'{API}/repos/{repo}/contents/{path}', headers=GHH, json=body)
    pr = requests.post(f'{API}/repos/{repo}/pulls', headers=GHH, json={'title': message, 'head': branch, 'base': base, 'body': 'Created by AI bot'}).json()
    return pr.get('html_url', pr)


FUNCS = {'list_repos': t_list_repos, 'list_files': t_list_files, 'read_file': t_read_file, 'propose_change': t_propose_change}
S = lambda props, req: {'type': 'OBJECT', 'properties': {k: {'type': 'STRING'} for k in props}, 'required': req}
DECLS = [
    {'name': 'list_repos', 'description': 'List the user GitHub repositories'},
    {'name': 'list_files', 'description': 'List files in a repo folder', 'parameters': S(['repo', 'path'], ['repo'])},
    {'name': 'read_file', 'description': 'Read a file from a repo', 'parameters': S(['repo', 'path'], ['repo', 'path'])},
    {'name': 'propose_change', 'description': 'Write a full file on a new branch and open a Pull Request (user merges it). repo is owner/name.', 'parameters': S(['repo', 'path', 'content', 'message'], ['repo', 'path', 'content', 'message'])},
]
SYSTEM = 'You are a friendly assistant that does GitHub work for a user who cannot code. Reply in the same language as the user (often Sinhala). Keep answers short and simple. Use the tools. Changes are only proposed as Pull Requests; tell the user to merge the PR link if they approve.'


def ask(text):
    contents = [{'role': 'user', 'parts': [{'text': text}]}]
    for _ in range(8):
        r = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent',
                          headers={'x-goog-api-key': GEM}, timeout=120,
                          json={'contents': contents, 'systemInstruction': {'parts': [{'text': SYSTEM}]}, 'tools': [{'functionDeclarations': DECLS}]}).json()
        try:
            parts = r['candidates'][0]['content']['parts']
        except Exception:
            return 'AI error: ' + json.dumps(r)[:300]
        calls = [p['functionCall'] for p in parts if 'functionCall' in p]
        if not calls:
            return ''.join(p.get('text', '') for p in parts) or '...'
        contents.append({'role': 'model', 'parts': parts})
        res = []
        for c in calls:
            try:
                out = FUNCS[c['name']](**c.get('args', {}))
            except Exception as e:
                out = 'error: ' + str(e)
            res.append({'functionResponse': {'name': c['name'], 'response': {'result': out}}})
        contents.append({'role': 'user', 'parts': res})
    return 'Too many steps.'


def main():
    end = time.time() + int(os.environ.get('RUN_SECONDS', '240'))
    offset = None
    while time.time() < end:
        r = tg('getUpdates', offset=offset, timeout=25)
        for u in r.get('result', []):
            offset = u['update_id'] + 1
            m = u.get('message') or {}
            chat = str(m.get('chat', {}).get('id', ''))
            text = m.get('text')
            if not text:
                continue
            if not ALLOWED or chat != ALLOWED:
                say(chat, f'Not allowed. Your chat id: {chat}')
                continue
            say(chat, ask(text))
    if offset:
        tg('getUpdates', offset=offset, timeout=0)


main()
