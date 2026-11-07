"""Turn judged output into the deliverables: ranked promos (CSV + markdown) and an auto-flagged failure list.
Usage: python make_report.py stage2_gemini.json"""
import json, csv, sys
src = sys.argv[1] if len(sys.argv) > 1 else 'stage2_gemini.json'
rows = json.load(open(src))
ok = [r for r in rows if r['judge']['valid']]
for r in ok: r['_w'] = r['trimmed'] if r.get('trim_ok') else r['segments'][0]
ok.sort(key=lambda r: -r['final_score_100'])
fmt = lambda s: f"{int(s//60)}:{s%60:05.2f}"

with open('promos_ranked.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['post_order','episode','start','end','duration_s','score_100','hook','cliffhanger','standalone','conflict_rule','pacing_rule','archetype','hook_quote','cliffhanger_quote','why_it_works','what_happens','window_source'])
    for i, r in enumerate(ok, 1):
        j = r['judge']['raw']; b = r['llm_breakdown_0_10']; s = r['_w']
        w.writerow([i, r['episode'], s['start'], s['end'], round(s['end']-s['start'], 1), r['final_score_100'], b['hook'], b['cliffhanger'], b['standalone'], b['conflict(rule)'], b['pacing(rule)'], r['archetype_llm'], j['hook']['evidence'], j['cliffhanger']['evidence'], j['why_it_works'], j['what_happens'], 'LLM-trimmed' if r.get('trim_ok') else 'stage-1 window'])

md = [f"# Ranked promos ({len(ok)} judged of {len(rows)} candidates)\n", f"Model: {rows[0]['judge']['model']}. Scores: 0-100 = hook 25% + cliffhanger 30% + standalone 20% (LLM) + conflict 15% + pacing 10% (rules).\n"]
for i, r in enumerate(ok[:15], 1):
    j = r['judge']['raw']; s = r['_w']; b = r['llm_breakdown_0_10']
    md.append(f"## {i}. Episode {r['episode']} | {fmt(s['start'])}-{fmt(s['end'])} ({s['end']-s['start']:.0f}s) | {r['final_score_100']}/100 | {r['archetype_llm']}\n"
              f"- Hook ({b['hook']}): \"{j['hook']['evidence']}\"\n- Cliffhanger ({b['cliffhanger']}): \"{j['cliffhanger']['evidence']}\" - {j['cliffhanger'].get('unresolved_question','')}\n"
              f"- Standalone ({b['standalone']}): {j['standalone'].get('confusions') or 'no confusions flagged'}\n- Why it works: {j['why_it_works']}\n- Summary: {j['what_happens']}\n")
open('promos_top15.md', 'w', encoding='utf-8').write('\n'.join(md))

# auto-flagged candidates for the failure log (a human still has to read these)
fl = ['# Auto-flagged for human review (possible bad picks)\n']
for r in rows:
    j = r['judge']
    if not j['valid']: fl.append(f"- ep{r['episode']} rank{r['rank']}: judge call FAILED - {j['problems'][:1]}"); continue
    b = r['llm_breakdown_0_10']; why = []
    if b['standalone'] <= 4: why.append(f"low standalone ({b['standalone']}): {j['raw']['standalone'].get('confusions')}")
    if b['hook'] <= 4: why.append(f"weak hook ({b['hook']})")
    if b['cliffhanger'] <= 4: why.append(f"weak cliffhanger ({b['cliffhanger']})")
    if not r.get('trim_ok'): why.append('LLM trim fell outside 20-60s, used stage-1 window')
    if r['archetype'] != r['archetype_llm']: why.append(f"archetype disagreement rules='{r['archetype']}' vs LLM='{r['archetype_llm']}'")
    if why: fl.append(f"- ep{r['episode']} {r['_w']['start'] if '_w' in r else ''} score {r['final_score_100']}: " + '; '.join(why))
open('failures_auto.md', 'w', encoding='utf-8').write('\n'.join(fl))
agree = sum(r['archetype'] == r['archetype_llm'] for r in ok)
print(f'{len(ok)}/{len(rows)} valid | archetype rules-vs-LLM agreement {agree}/{len(ok)} | wrote promos_ranked.csv, promos_top15.md, failures_auto.md')
