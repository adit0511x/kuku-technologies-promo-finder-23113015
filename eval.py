"""Evaluate tool output against human blind picks (my_picks.json). No training; the picks are test data only.
Usage: python eval.py                      -> stage-1 (rules)
       python eval.py stage2_gemini.json   -> LLM-judged output"""
import json, sys, bisect
picks = json.load(open('my_picks.json')); P = {p['id']: p for p in picks['picks']}
src = sys.argv[1] if len(sys.argv) > 1 else 'stage1_promos.json'
tool = json.load(open(src))
tool = [t for t in tool if 'judge' not in t or t['judge']['valid']]   # only clips the LLM actually judged (ranks are within this set)
for t in tool:                                    # uniform view of each tool promo: window, score
    seg = t['trimmed'] if t.get('trim_ok') else t['segments'][0]
    t['_w'] = (seg['start'], seg['end']); t['_s'] = t.get('final_score_100', t['total_score_100'])
tool.sort(key=lambda t: -t['_s'])
for i, t in enumerate(tool, 1): t['_rank'] = i

def iou_cov(a, b):
    ov = max(0, min(a[1], b[1]) - max(a[0], b[0])); u = (a[1]-a[0]) + (b[1]-b[0]) - ov
    return ov / u, ov / (a[1]-a[0])               # IoU, share of the HUMAN window covered by the tool window

rows, match = [], {}
for pid, p in P.items():
    h = (p['start'], p['end']); best = None
    for t in tool:
        if t['episode'] != p['episode']: continue
        iou, cov = iou_cov(h, t['_w'])
        if best is None or iou > best[0]: best = (iou, cov, t)
    iou, cov, t = best if best else (0, 0, None)
    match[pid] = t
    rows.append((pid, h, t['_w'] if t else None, round(iou, 2), round(cov, 2), t['_rank'] if t else None))
print(f'source: {src}   tool promos: {len(tool)}   human picks: {len(P)}\n')
print(f"{'id':5} {'human':>14} {'best tool window':>18} {'IoU':>5} {'cover':>6} {'tool rank':>9}")
for r in rows: print(f"{r[0]:5} {str(r[1]):>14} {str(r[2]):>18} {r[3]:>5} {r[4]:>6} {str(r[5]):>9}")
n = len(rows)
print(f"\ncovered>=80% by some tool window: {sum(r[4] >= .8 for r in rows)}/{n}   IoU>=0.5 (tight agreement): {sum(r[3] >= .5 for r in rows)}/{n}   IoU>=0.3: {sum(r[3] >= .3 for r in rows)}/{n}")
print('\nHUMAN TOP 3 -> where the tool ranks the matching promo:')
for k, pid in enumerate(picks['top3'], 1):
    t = match[pid]; print(f"  human #{k} {pid}: tool rank {t['_rank'] if t else 'none'} of {len(tool)}" + (f" (score {t['_s']})" if t else ''))
tops = [match[p]['_rank'] for p in picks['top3'] if match[p]]
print(f"  of human top-3, matched inside tool top 10: {sum(r<=10 for r in tops)}/3, top 20: {sum(r<=20 for r in tops)}/3, top 50: {sum(r<=50 for r in tops)}/3")
