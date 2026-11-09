#!/usr/bin/env python3
"""Extract operator-authored prompts from every local agent service into one JSONL corpus.
Only human-typed turns are kept; subagent sessions, system reminders and inter-agent messages are dropped."""
import glob, json, os, re, sqlite3, subprocess, sys
from datetime import datetime, timezone

H = os.path.expanduser('~')
OUT = sys.argv[1]
out = open(OUT, 'w')
counts = {}

def emit(src, sess, ts, cwd, text):
    text = (text or '').strip()
    if not text or len(text) < 2:
        return
    if text.startswith(('<system-reminder', '<environment_context', '<user_info', '<recommended_plugins',
                        '<permissions', '<turn_aborted', '# AGENTS.md', '<INSTRUCTIONS', 'Caveat:', '<local-command',
                        '<command-name', '<task-notification', '[Message] timestamp=', 'The interruption was environmental')):
        return
    counts[src] = counts.get(src, 0) + 1
    out.write(json.dumps({'src': src, 'session': sess, 'ts': ts, 'cwd': cwd, 'text': text[:6000]}) + '\n')

def ro(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)

# ---- Antigravity (IDE + CLI): step_type 14 = user input, protobuf payload
UUID = re.compile(rb'^[\s\S]{0,3}\$?[0-9a-f-]{32,36}$')
for f in glob.glob(f'{H}/.gemini/antigravity*/conversations/*.db'):
    src = 'antigravity-cli' if 'antigravity-cli' in f else 'antigravity'
    try:
        db = ro(f)
        for idx, p in db.execute('select idx, step_payload from steps where step_type=14 order by idx'):
            strs = [s for s in re.findall(rb'[\x20-\x7e\n\t\xc2-\xf4\x80-\xbf]{6,}', p or b'')]
            strs = [s.decode('utf8', 'ignore') for s in strs if not re.fullmatch(rb'[\s\S]{0,4}[0-9a-f-]{20,40}', s)]
            strs = [s for s in strs if not re.fullmatch(r'.{0,3}[0-9a-f]{32}', s.strip())]
            if strs:
                t = max(strs, key=len)
                emit(src, os.path.basename(f)[:-3], None, None, re.sub(r'^[^\w/@"\'(\[<*#-]{1,3}', '', t))
    except Exception as e:
        print('ag err', f, e, file=sys.stderr)

# ---- Codex: rollout jsonl(.zst); skip subagent threads
for f in glob.glob(f'{H}/.codex/sessions/**/*.jsonl*', recursive=True) + glob.glob(f'{H}/.codex/archived_sessions/*.jsonl*'):
    try:
        raw = subprocess.run(['zstd', '-dc', f], capture_output=True).stdout if f.endswith('.zst') else open(f, 'rb').read()
    except Exception:
        continue
    sub = False; cwd = None; sess = os.path.basename(f)
    for line in raw.decode('utf8', 'ignore').splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        p = o.get('payload') or {}
        if o.get('type') == 'session_meta':
            sub = p.get('thread_source') == 'subagent' or bool((p.get('source') or {}).get('subagent') if isinstance(p.get('source'), dict) else False)
            cwd = p.get('cwd'); sess = p.get('id', sess)
            if p.get('originator') == 'codex_exec':
                sub = True  # non-interactive exec runs are scripted, not typed
        if sub:
            break
        if o.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user':
            for c in p.get('content') or []:
                if c.get('type') == 'input_text':
                    emit('codex', sess, o.get('timestamp'), cwd, c.get('text'))

# ---- Cursor: ~/.cursor/chats/*/*/store.db blobs (JSON messages)
for f in glob.glob(f'{H}/.cursor/chats/*/*/store.db'):
    try:
        meta = json.load(open(os.path.join(os.path.dirname(f), 'meta.json')))
    except Exception:
        meta = {}
    try:
        db = ro(f)
        for (data,) in db.execute('select data from blobs'):
            if not data or data[:1] != b'{':
                continue
            try:
                o = json.loads(data)
            except Exception:
                continue
            if o.get('role') != 'user':
                continue
            c = o.get('content')
            if isinstance(c, list):
                c = '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
            m = re.findall(r'<user_query>\s*([\s\S]*?)\s*</user_query>', c or '')
            for q in m:
                emit('cursor', os.path.basename(os.path.dirname(f)), meta.get('createdAtMs'), meta.get('cwd'), q)
    except Exception as e:
        print('cursor err', f, e, file=sys.stderr)

# ---- MiniMax: v2 sessions messages.jsonl, root sessions only
for f in glob.glob(f'{H}/.minimax/v2/sessions/**/messages.jsonl', recursive=True):
    root = None
    for line in open(f, errors='ignore'):
        try:
            o = json.loads(line)
        except Exception:
            continue
        m = o.get('message') or {}
        if m.get('role') != 'user':
            continue
        parts = m.get('content') if isinstance(m.get('content'), list) else [{'type': 'text', 'text': m.get('content')}]
        for c in parts:
            t = c.get('text') if isinstance(c, dict) else None
            if not t:
                continue
            if root is None and 'SESSION ROLE:' in t:
                root = 'SESSION ROLE: root' in t
            if root is False:
                break
            emit('minimax', f.split('/')[-2], o.get('created_at') or o.get('timestamp'), None, t)

# ---- MiMo (Xiaomi MiMo AI desktop + mimocode CLI share mimocode.db)
try:
    db = ro(f'{H}/.local/share/mimocode/mimocode.db')
    q = '''select m.session_id, m.time_created, s.directory, s.parent_id, p.data
           from message m join part p on p.message_id=m.id join session s on s.id=m.session_id
           where json_extract(m.data,'$.role')='user' and m.agent_id='main' order by m.time_created'''
    for sess, ts, d, parent, pdata in db.execute(q):
        if parent:
            continue
        try:
            pj = json.loads(pdata)
        except Exception:
            continue
        if pj.get('type') == 'text' and not pj.get('synthetic'):
            emit('mimo', sess, ts, d, pj.get('text'))
except Exception as e:
    print('mimo err', e, file=sys.stderr)

# ---- Muse: root session.jsonl runtime.user_intent.accepted
for f in glob.glob(f'{H}/.local/share/muse/sessions/20*/*/*/*/session.jsonl'):
    for line in open(f, errors='ignore'):
        if 'runtime.user_intent.accepted' not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        p = o.get('payload') or {}
        if (p.get('semantic_kind') or {}).get('kind') not in (None, 'chat'):
            continue
        t = '\n'.join(b.get('text', '') for b in p.get('refill_blocks') or [] if b.get('kind') == 'text')
        emit('muse', f.split('/')[-2], o.get('recorded_at'), None, t)

# ---- Claude Code: ~/.claude/projects/*/*.jsonl (top-level sessions only)
for f in glob.glob(f'{H}/.claude/projects/*/*.jsonl'):
    for line in open(f, errors='ignore'):
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get('type') != 'user' or o.get('isSidechain') or o.get('isMeta'):
            continue
        c = (o.get('message') or {}).get('content')
        if isinstance(c, list):
            c = '\n'.join(x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text')
        emit('claude-code', o.get('sessionId'), o.get('timestamp'), o.get('cwd'), c)

print(json.dumps(counts), file=sys.stderr)
