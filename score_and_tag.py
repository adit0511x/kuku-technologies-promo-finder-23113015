"""Stage 1b: composite score (0-100) with visible breakdown + archetype tagging. Pure code, no LLM.
Every number here is a rule-based PROXY. The LLM judge (stage 2) re-scores hook / cliffhanger / standalone."""
import json, re, csv
from candidates import gen_episode, validate, pick_nonoverlap

# ---- weights (sum = 100). Mirrors Kuku's definition: hook, cliffhanger, standalone, + engagement proxies
TOP_N = None  # None = keep every episode's best (max 2 per episode); no global cutoff
WEIGHTS = {'hook': 25, 'cliffhanger': 30, 'standalone': 20, 'conflict': 15, 'pacing': 10}

# ---- archetypes: (name, one-line meaning, regex). Highest keyword count wins; runner-up reported as secondary.
ARCHETYPES = {
 'Public Humiliation / Betrayal': (r"\b(abandon\w*|humiliat\w*|disgrace\w*|shame\w*|altar|plain(ness)?|worthless|low value|beneath|mock\w*|laugh\w*|cast out|disown\w*|condemn\w*|betray\w*)\b"),
 'Hidden Identity Reveal':        (r"\b(duke|true|identity|title|heir|salute\w*|bow\w*|kneel\w*|your grace|alive|dead|ambush|mysterious|stranger|scar\w*|who are you|revealed?)\b"),
 'Revenge / Comeuppance':         (r"\b(arrest\w*|guilty|expos\w*|evidence|confess\w*|judge|trial|justice|punish\w*|pay for|consequence\w*|constable|crown|prove\w*|forg\w*)\b"),
 'Forbidden Romance / Intimacy':  (r"\b(kiss\w*|love|desire|embrace\w*|passion|bed|touch\w*|heart|husband|wife|bride|darling|lips|tender\w*)\b"),
 'Danger / Life-or-Death Threat': (r"\b(sword|dagger|knife|blood|kill\w*|murder\w*|poison\w*|dungeon|guard\w*|attack\w*|die|death|weapon|threat\w*|escape|run)\b"),
 'Secret / Conspiracy':           (r"\b(secret\w*|plot\w*|scheme\w*|whisper\w*|letter|informant|spy|conspir\w*|hide|hidden|lie[sd]?|liar|deceiv\w*|bribe\w*|silence)\b"),
}
ARCH_MEANING = {
 'Public Humiliation / Betrayal': 'Heroine is shamed or betrayed in front of others, which drives sympathy and anger.',
 'Hidden Identity Reveal': 'A character turns out to be someone far more powerful than assumed.',
 'Revenge / Comeuppance': 'A villain is exposed, arrested or made to pay.',
 'Forbidden Romance / Intimacy': 'Tension or intimacy between leads or a taboo couple.',
 'Danger / Life-or-Death Threat': 'Physical peril or violence raises the stakes immediately.',
 'Secret / Conspiracy': 'Hidden plots, lies or whispered schemes the viewer wants unraveled.',
 'Power Showdown': 'Fallback: a heated confrontation with no stronger archetype signal.',
}
GENERIC = re.compile(r"\b(LORD|NOBLEMAN|NOBLEWOMAN|MAN|WOMAN|MAID|OFFICIAL|GUARD|STRANGER|GROOM|MATRIARCH|PRIEST|VILLAGER|THUG|INFORMANT|CONSTABLE|HOUSEKEEPER|MOTHER|ELDER|LADY IN)\b")
CONJ_START = re.compile(r'^\W*(and|but|because|so|then|or|which|that|he|she|they|it|him|her)\b', re.I)

def tag_archetype(text):
    sc = {k: len(re.findall(v, text, re.I)) for k, v in ARCHETYPES.items()}
    ranked = sorted(sc.items(), key=lambda kv: -kv[1])
    if ranked[0][1] < 3: return 'Power Showdown', None, sc
    sec = ranked[1][0] if ranked[1][1] >= max(3, 0.6 * ranked[0][1]) else None
    return ranked[0][0], sec, sc

def standalone_proxy(dlg):
    """0-10. Penalise: generic/unnamed speakers, too many speakers, clip opening mid-sentence."""
    speakers = {e['speaker'] for e in dlg}
    generic = [s for s in speakers if GENERIC.search(s)]
    s = 10.0
    s -= 2.0 * len(generic)                       # confusing 'BLOND NOBLEMAN' type labels
    s -= 0.7 * max(0, len(speakers) - 3)          # crowded cast = hard to follow
    if CONJ_START.match(dlg[0]['text']): s -= 2.5 # opens as a reply to something unseen
    return max(0.0, min(10.0, s)), sorted(generic)

def breakdown(c, window_dlg):
    f = c['features']
    parts = {
      'hook':        min(f['hook'] / 2.5, 1) * 10,
      'cliffhanger': max(0, min(f['cliff'] / 3.0, 1)) * 10,
      'standalone':  standalone_proxy(window_dlg)[0],
      'conflict':    min(f['conflict'] / 1.0, 1) * 10,
      'pacing':      0.6 * min(f['density'] / 0.35, 1) * 10 + 0.4 * max(0, 1 - abs(c['duration'] - 42) / 22) * 10,
    }
    total = sum(WEIGHTS[k] * parts[k] / 10 for k in WEIGHTS)
    return {k: round(v, 1) for k, v in parts.items()}, round(total, 1)

def run(parsed='parsed.json'):
    import os, sys
    if not os.path.exists(parsed): sys.exit('parsed.json not found. Run first:  python parse.py "."   (or give the episodes folder path)')
    eps = json.load(open(parsed)); by = {e['num']: e for e in eps}
    raw = [c for e in eps for c in gen_episode(e)]
    valid = [c for c in raw if not validate(c, by)]
    for c in valid:                                  # score every candidate (cheap)
        sg = c['segments'][0]; ep = by[sg['episode']]
        evs = [e for s in ep['scenes'] for e in s['events'] if e['start'] >= sg['start']-1e-6 and e['end'] <= sg['end']+1e-6]
        dlg = [e for e in evs if e['type'] == 'DIALOGUE']
        c['parts'], c['total'] = breakdown(c, dlg)
        c['_dlg'] = dlg; c['_text'] = ' '.join(e['text'] for e in evs)
    for c in valid: c['score'] = c['total']          # pick_nonoverlap ranks by 'score'
    short = sorted(pick_nonoverlap(valid, per_ep=2), key=lambda c: -c['total'])[:TOP_N]
    out = []
    for rank, c in enumerate(short, 1):
        a, b, _ = tag_archetype(c['_text']); generic = standalone_proxy(c['_dlg'])[1]
        sg = c['segments'][0]
        out.append({'rank': rank, 'episode': sg['episode'], 'segments': c['segments'], 'duration': c['duration'],
            'total_score_100': c['total'], 'breakdown_0_10': c['parts'], 'weights': WEIGHTS,
            'archetype': a, 'archetype_meaning': ARCH_MEANING[a], 'secondary_archetype': b,
            'hook_line': f"{c['_dlg'][0]['speaker']}: {c['_dlg'][0]['text']}",
            'cliffhanger_line': f"{c['_dlg'][-1]['speaker']}: {c['_dlg'][-1]['text']}",
            'standalone_flags': ('unnamed speakers: ' + ', '.join(generic)) if generic else '',
            'status': 'rule-based draft; awaiting LLM judge'})
    json.dump(out, open('stage1_promos.json', 'w'), indent=1)
    with open('stage1_promos.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['rank','episode','start','end','dur_s','score_100','hook','cliffhanger','standalone','conflict','pacing','archetype','secondary','hook_line','cliffhanger_line','flags'])
        for o in out:
            s = o['segments'][0]; p = o['breakdown_0_10']
            w.writerow([o['rank'], o['episode'], s['start'], s['end'], o['duration'], o['total_score_100'], p['hook'], p['cliffhanger'], p['standalone'], p['conflict'], p['pacing'], o['archetype'], o['secondary_archetype'] or '', o['hook_line'], o['cliffhanger_line'], o['standalone_flags']])
    return out, len(raw), len(valid)

if __name__ == '__main__':
    out, nr, nv = run(); print('candidates', nr, 'valid', nv, 'shortlist', len(out))
    from collections import Counter; print(Counter(o['archetype'] for o in out))
    for o in out[:10]:
        s = o['segments'][0]; p = o['breakdown_0_10']
        print(f"#{o['rank']} ep{o['episode']} {s['start']}-{s['end']} {o['total_score_100']}/100 [{o['archetype']}] H{p['hook']} C{p['cliffhanger']} S{p['standalone']} X{p['conflict']} P{p['pacing']}  {o['standalone_flags']}")
