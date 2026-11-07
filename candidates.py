"""Stage 1 (pure code, no LLM): generate + validate + cheap-score candidate promo windows."""
import json, re
MIN_D, MAX_D = 20.0, 60.0
HOOK_WORDS = r"\b(slap|gun|knife|blood|dead|die|kill|murder|pregnant|divorce|annul|duke|king|queen|prince|traitor|liar|lied|secret|truth|poison|arrest|guards?|escape|betray\w*|marry|married|wedding|shame|forgive|never|how dare|get out|leave|you\s+are\s+not|who are you|who is|what did you)\b"
CLIFF_WORDS = r"\b(gasp|silence|freeze|frozen|stunned|shock\w*|door|footsteps|knock|burst|enter\w*|appear\w*|reveal\w*|turn\w* to|stares?|horror|terrified|ominous|cut to black)\b"

def flatten(ep):
    """Timeline units in absolute episode time. Dialogue = speech; ACTION/SFX kept as context."""
    ev = [e for s in ep['scenes'] for e in s['events']]
    return sorted(ev, key=lambda e: (e['start'], e['end']))

def window_text(evs, a, b):
    return [e for e in evs if e['start'] >= a - 1e-6 and e['end'] <= b + 1e-6]

def validate(p, eps_by_num):
    """Hard checks. Every promo must pass or it is dropped. Returns list of problems."""
    errs, tot = [], 0.0
    if not p['segments']: return ['no segments']
    prev = None
    for sg in p['segments']:
        ep = eps_by_num.get(sg['episode'])
        if ep is None: errs.append(f"unknown episode {sg['episode']}"); continue
        if not (0 <= sg['start'] < sg['end'] <= ep['duration'] + 0.01): errs.append(f"ep{sg['episode']} times out of range")
        tot += sg['end'] - sg['start']
        key = (sg['episode'], sg['start'])
        if prev and key <= prev: errs.append('segments not in order')
        prev = key
    if not (MIN_D <= tot <= MAX_D): errs.append(f'duration {tot:.1f}s outside {MIN_D}-{MAX_D}')
    return errs

def gen_episode(ep):
    evs = flatten(ep); dur = ep['duration']
    dlg = [e for e in evs if e['type'] == 'DIALOGUE']
    if not dlg: return []
    starts = sorted({e['start'] for e in evs if e['type'] in ('DIALOGUE', 'CAMERA')})   # clip may open on a line or a shot
    ends = sorted({e['end'] for e in dlg} | {dur})                                       # clip must end on a spoken line or episode end
    out = []
    for a in starts:
        for b in ends:
            d = b - a
            if d < MIN_D or d > MAX_D: continue
            w = window_text(evs, a, b)
            wd = [e for e in w if e['type'] == 'DIALOGUE']
            if len(wd) < 4: continue
            # --- cheap features ---
            first3 = ' '.join(e['text'] for e in w if e['start'] < a + 3.0 and e['type'] in ('DIALOGUE','ACTION'))
            hook = 0.0
            hook += 1.0 * bool(re.search(r'[!?]', ' '.join(e['text'] for e in wd if e['start'] < a + 3.5)))
            hook += 1.0 * bool(re.search(HOOK_WORDS, first3, re.I))
            hook += 0.5 * any(e['type']=='DIALOGUE' and e['start'] <= a + 1.5 for e in w)      # speech right away, not slow open
            last = [e for e in w if e['type']=='DIALOGUE'][-1]
            tail = ' '.join(e['text'] for e in w if e['start'] >= b - 5)
            cliff = 0.0
            if abs(b - dur) < 0.6: cliff += 2.0                                                # ends the episode: the show's own cliffhanger
            cliff += 1.0 * bool(re.search(r'(\?|\.\.\.|!)\s*$', last['text']))
            cliff += 0.5 * bool(re.search(CLIFF_WORDS, tail, re.I))
            cliff -= 1.0 * bool(re.search(r'\b(thank you|farewell|goodnight|good night|i forgive|at last|finally)\b', last['text'], re.I))  # resolution language
            density = len(wd) / d
            conflict = sum(len(re.findall(r'[!?]', e['text'])) for e in wd) / max(1, len(wd))
            score = 1.2*hook + 1.5*cliff + 0.8*min(conflict, 1.5) + 0.5*min(density/0.4, 1.5)
            # prefer natural length ~35-50s
            score -= 0.4 * (abs(d - 42) / 20)
            out.append({'episode': ep['num'], 'segments': [{'episode': ep['num'], 'start': round(a,2), 'end': round(b,2)}],
                        'duration': round(d,2), 'score': round(score,3),
                        'features': {'hook': round(hook,2), 'cliff': round(cliff,2), 'conflict': round(conflict,2), 'density': round(density,2)}})
    return out

def pick_nonoverlap(cands, per_ep=3, min_gap=0.0):
    """Greedy: best-first, no two promos from the same episode overlap; cap per episode."""
    cands = sorted(cands, key=lambda c: -c['score']); kept = []
    for c in cands:
        s = c['segments'][0]
        if sum(k['episode']==c['episode'] for k in kept) >= per_ep: continue
        if any(k['episode']==c['episode'] and not (s['end'] <= k['segments'][0]['start']-min_gap or s['start'] >= k['segments'][0]['end']+min_gap) for k in kept): continue
        kept.append(c)
    return kept

if __name__ == '__main__':
    eps = json.load(open('parsed.json')); by = {e['num']: e for e in eps}
    allc, dropped = [], 0
    for ep in eps:
        for c in gen_episode(ep):
            (allc if not validate(c, by) else []).append(c) if True else None
    # validation pass counted explicitly
    raw = [c for ep in eps for c in gen_episode(ep)]
    valid = [c for c in raw if not validate(c, by)]
    print('raw candidates', len(raw), 'valid', len(valid))
    short = pick_nonoverlap(valid, per_ep=2)
    top = sorted(short, key=lambda c: -c['score'])[:40]
    json.dump(top, open('shortlist.json','w'), indent=1)
    for c in top[:12]:
        s=c['segments'][0]; print(f"ep{c['episode']:>2} {s['start']:>6.1f}-{s['end']:>6.1f} ({c['duration']:.0f}s) score {c['score']:.2f} {c['features']}")
