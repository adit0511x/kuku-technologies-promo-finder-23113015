"""Stage 2: LLM judge. Model-agnostic (config.json), cached, schema-validated, with hallucination guards.
Usage:  GEMINI_API_KEY=... python judge.py --provider gemini      (real)
        python judge.py --provider mock                            (no key; pipeline test only)"""
import json, os, re, sys, hashlib, time, argparse, urllib.request, urllib.error
from score_and_tag import ARCHETYPES, WEIGHTS

def load_env(path='.env'):
    """Minimal .env reader: KEY=value lines. Real environment variables win. Keeps the key out of code."""
    if os.path.exists(path):
        for ln in open(path, encoding='utf-8'):
            ln = ln.strip()
            if ln and not ln.startswith('#') and '=' in ln:
                k, v = ln.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
load_env()

ARCH_LIST = list(ARCHETYPES) + ['Power Showdown']
SYSTEM = f"""You are a short-drama promo editor for vertical microdrama apps (ReelShort, DramaBox style).
You are shown ONLY the text of one candidate clip, as a cold viewer would experience it: no logline, no earlier episodes.
A good promo (20-60s) has: (1) a HOOK in its first 3 seconds that stops a scrolling viewer, (2) a CLIFFHANGER ending that is unresolved,
(3) STANDALONE sense: a stranger understands who is who and what is at stake.
Be strict. Most clips deserve 4-7. Reserve 9-10 for exceptional ones. Do not inflate scores.
Every evidence field MUST be an exact quote copied from the clip. Never invent lines or timestamps.
Return ONLY JSON with keys:
what_happens (<=2 sentences, written as if you know nothing else about the show),
who_are_they (who you can identify from the clip alone; say 'unclear' if you cannot),
hook {{score 0-10, evidence (exact quote from first ~3s), why}},
cliffhanger {{score 0-10, evidence (exact quote from the end), unresolved_question}},
standalone {{score 0-10, confusions (list of things a newcomer would not understand)}},
archetype (one of {ARCH_LIST}),
why_it_works (ONE line),
trim {{start_line (index of best opening line), end_line (index of best closing line)}} (indices from the numbered list)."""

def render_clip(ep, a, b):
    """Numbered lines w/ clip-relative seconds. Dialogue + ACTION + SOUND FX only (CAMERA is visual noise/tokens)."""
    evs = sorted([e for s in ep['scenes'] for e in s['events'] if e['start'] >= a-1e-6 and e['end'] <= b+1e-6 and e['type'] != 'CAMERA'], key=lambda e: e['start'])
    lines, idx = [], []
    for e in evs:
        i = len(lines)
        tag = e['speaker'] if e['type'] == 'DIALOGUE' else f"[{e['type']}]"
        lines.append(f"{i}. ({e['start']-a:.1f}s) {tag}: {e['text']}"); idx.append(e)
    return '\n'.join(lines), idx

# ---------- providers ----------
def get_key(cfg):
    k = os.environ.get(cfg['api_key_env'])
    if not k: sys.exit(f"Missing {cfg['api_key_env']}. Put it in a .env file next to judge.py, or set it in the terminal.")
    return k

def http_json(req):
    try: return json.load(urllib.request.urlopen(req, timeout=90))
    except urllib.error.HTTPError as e: raise RuntimeError(f'HTTP {e.code}: ' + e.read().decode('utf-8', 'ignore')[:300])

def call_gemini(cfg, prompt):
    key = get_key(cfg)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": cfg['temperature'], "responseMimeType": "application/json"}}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", "x-goog-api-key": key})
    return http_json(req)['candidates'][0]['content']['parts'][0]['text']

def call_openrouter(cfg, prompt):
    key = get_key(cfg)
    body = {"model": cfg['model'], "temperature": cfg['temperature'], "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    return http_json(req)['choices'][0]['message']['content']

def call_mock(cfg, prompt, promo=None, idx=None):
    """Deterministic stand-in so the pipeline can be tested without a key. NOT a real judgement: scores are copied from stage-1 rules."""
    p = promo['breakdown_0_10']; dl = [e for e in idx if e['type'] == 'DIALOGUE']
    return json.dumps({"what_happens": "[mock] no real summary", "who_are_they": "[mock]",
        "hook": {"score": p['hook'], "evidence": dl[0]['text'], "why": "[mock]"},
        "cliffhanger": {"score": p['cliffhanger'], "evidence": dl[-1]['text'], "unresolved_question": "[mock]"},
        "standalone": {"score": p['standalone'], "confusions": []}, "archetype": promo['archetype'],
        "why_it_works": "[mock] rule-based stand-in", "trim": {"start_line": 0, "end_line": len(idx)-1}})

PROVIDERS = {'gemini': call_gemini, 'openrouter': call_openrouter}

# ---------- guards ----------
def norm(s): return re.sub(r'\W+', ' ', s.lower()).strip()

def check(r, idx, clip_text):
    """Return list of problems; any problem => retry / flag. Quotes must really be in the clip; indices must be valid."""
    errs = []
    for k in ('hook', 'cliffhanger', 'standalone'):
        if k not in r or not isinstance(r[k].get('score'), (int, float)) or not 0 <= r[k]['score'] <= 10: errs.append(f'bad {k} score')
    for k in ('hook', 'cliffhanger'):
        q = r.get(k, {}).get('evidence', '')
        whole_line = norm(q) in {norm(e['text']) for e in idx}
        if not whole_line and (len(norm(q).split()) < 2 or norm(q) not in norm(clip_text)): errs.append(f'{k} evidence not found verbatim in clip (possible invention)')
    if r.get('archetype') not in ARCH_LIST: errs.append('archetype not in allowed list')
    t = r.get('trim', {}); n = len(idx)
    if not (isinstance(t.get('start_line'), int) and isinstance(t.get('end_line'), int) and 0 <= t['start_line'] < t['end_line'] < n): errs.append('trim indices invalid')
    return errs

def run(provider, eps_path='parsed.json', promos_path='stage1_promos.json', limit=None, only_eps=None, progress=None):
    for need, step in (('parsed.json', 'python parse.py "."'), ('stage1_promos.json', 'python score_and_tag.py')):
        if not os.path.exists(need): sys.exit(f'{need} not found. Run first:  {step}')
    cfgfile = json.load(open('config.json')); cfg = dict(cfgfile['providers'][provider]); cfg['temperature'] = cfgfile['temperature']
    eps = {e['num']: e for e in json.load(open(eps_path))}; promos = json.load(open(promos_path))
    if only_eps: promos = [p for p in promos if p['episode'] in only_eps]
    promos = promos[:limit]
    delay = cfgfile.get('request_delay_s', 7); consec429 = 0
    os.makedirs('cache', exist_ok=True); out = []
    for n_done, pr in enumerate(promos, 1):
        sg = pr['segments'][0]; ep = eps[sg['episode']]
        print(f"[{n_done}/{len(promos)}] ep{sg['episode']} {sg['start']}-{sg['end']} ...", flush=True)
        if progress: progress(n_done, len(promos), sg['episode'])
        clip, idx = render_clip(ep, sg['start'], sg['end'])
        prompt = f"CLIP ({pr['duration']:.0f}s):\n{clip}"
        ck = f"cache/{hashlib.sha256((provider+cfg['model']+prompt).encode()).hexdigest()[:20]}.json"
        res, errs = None, []
        if os.path.exists(ck): res = json.load(open(ck)); errs = check(res, idx, clip)
        else:
            for attempt in range(cfgfile["max_retries"] + 1):
                try:
                    raw = call_mock(cfg, prompt, pr, idx) if provider == 'mock' else PROVIDERS[provider](cfg, prompt)
                    res = json.loads(re.sub(r'^```json|```$', '', raw.strip()).strip()); errs = check(res, idx, clip)
                    if not errs: break
                except Exception as ex:
                    errs = [f'call/parse error: {ex}']
                    time.sleep(45 if '429' in str(ex) else 2 * (attempt + 1))
            if res and not errs: json.dump(res, open(ck, 'w'))
            if provider != 'mock': time.sleep(delay)   # stay under the free-tier per-minute limit
        rec = dict(pr); rec['judge'] = {'provider': provider, 'model': cfg['model'], 'valid': not errs, 'problems': errs, 'raw': res}
        if res and not errs:
            h, c, s = res['hook']['score'], res['cliffhanger']['score'], res['standalone']['score']
            cx, pc = pr['breakdown_0_10']['conflict'], pr['breakdown_0_10']['pacing']
            rec['llm_breakdown_0_10'] = {'hook': h, 'cliffhanger': c, 'standalone': s, 'conflict(rule)': cx, 'pacing(rule)': pc}
            rec['final_score_100'] = round(sum(WEIGHTS[k] * v / 10 for k, v in zip(['hook','cliffhanger','standalone','conflict','pacing'], [h, c, s, cx, pc])), 1)
            rec['archetype_llm'] = res['archetype']
            t = res['trim']; tl = [e for e in idx][t['start_line']:t['end_line']+1]
            rec['trimmed'] = {'episode': sg['episode'], 'start': round(min(e['start'] for e in tl), 2), 'end': round(max(e['end'] for e in tl), 2)}
            rec['trimmed']['duration'] = round(rec['trimmed']['end'] - rec['trimmed']['start'], 2)
            rec['trim_ok'] = 20 <= rec['trimmed']['duration'] <= 60   # if false, fall back to the stage-1 window
        if errs: print(f"  FAILED ep{sg['episode']} (rank {pr['rank']}): {errs[0][:300]}")
        out.append(rec)
        consec429 = consec429 + 1 if (errs and '429' in errs[0]) else 0
        if consec429 >= 3: print('\nSTOPPING: 3 clips in a row hit the quota (429). Daily/minute limit is likely used up. Finished clips are cached; re-run later to continue.'); break
    json.dump(out, open(f'stage2_{provider}.json', 'w'), indent=1)
    ok = [r for r in out if r['judge']['valid']]
    print(f'{provider}: {len(ok)}/{len(out)} valid judgments; trims within 20-60s: {sum(r.get("trim_ok", False) for r in ok)}')
    return out

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--provider', default=None); ap.add_argument('--limit', type=int); ap.add_argument('--episodes', default=None, help='comma list, e.g. 5,14,22,33,47')
    a = ap.parse_args(); run(a.provider or json.load(open('config.json'))['provider'], limit=a.limit, only_eps={int(x) for x in a.episodes.split(',')} if a.episodes else None)
