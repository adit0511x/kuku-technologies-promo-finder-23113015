import json, os
import pandas as pd
import streamlit as st
from pipeline import run_pipeline, rank, APP_DIR

st.set_page_config(page_title='Promo Finder', page_icon='🎬', layout='wide')
cfg = json.load(open(os.path.join(APP_DIR, 'config.json')))
fmt = lambda s: f"{int(s // 60)}:{s % 60:05.2f}"

st.title('🎬 Promo Finder')
st.caption('Finds 20-60s promo clips (hook + cliffhanger + makes sense alone) in timestamped microdrama screenplays, scores them, and tags an archetype.')

with st.sidebar:
    st.header('Settings')
    provider = st.selectbox('Model provider', ['gemini', 'openrouter', 'mock'], help='mock = rule-based stand-in, for testing the pipeline only. It is NOT a judgement.')
    model = st.text_input('Model name', value=cfg['providers'].get(provider, {}).get('model', ''), disabled=(provider == 'mock'),
                          help='Model names change often. If you get 404 or a timeout, use a name your key can list.')
    key = ''
    if provider != 'mock':
        env_name = cfg['providers'][provider]['api_key_env']
        try: key = st.secrets.get(env_name, '')
        except Exception: key = ''
        key = st.text_input(f'{env_name}', value=key, type='password', help='Used only for this run. Not stored.') or os.environ.get(env_name, '')
    n_clips = st.slider('Clips to judge with the model', 3, 99, 10, help='The rule stage shortlists up to 2 per episode; the model judges the first N by rule score (or the episodes you list).')
    only = st.text_input('Only these episodes (optional)', placeholder='e.g. 5,14,22,33,47')
    delay = st.slider('Seconds between model calls', 0, 15, 7, help='Keeps free-tier quotas from returning 429.')
    st.info('Episode text is processed in a temporary folder for this run only. Do not upload content you are not allowed to share with the model provider.')

files = st.file_uploader('Upload episode .txt files, or one .zip of them', type=['txt', 'zip'], accept_multiple_files=True)
go = st.button('Find promos', type='primary', disabled=not files)

if go:
    if provider != 'mock' and not key: st.error('Enter an API key in the sidebar, or choose mock.'); st.stop()
    try: only_eps = {int(x) for x in only.split(',') if x.strip()} or None
    except ValueError: st.error('Episode list must be numbers separated by commas.'); st.stop()
    bar = st.progress(0.0, text='Parsing and shortlisting...')
    def cb(i, n, ep): bar.progress(i / n, text=f'Judging clip {i} of {n} (episode {ep})')
    try:
        out = run_pipeline([(f.name, f.getvalue()) for f in files], provider, model, key, n_clips, only_eps, delay, cb)
    except SystemExit as e: st.error(str(e)); st.stop()
    except Exception as e: st.error(f'Run failed: {e}'); st.stop()
    bar.empty(); st.session_state['out'] = out

out = st.session_state.get('out')
if out:
    ok = rank(out['judged']); bad = [r for r in out['judged'] if not r['judge']['valid']]
    c = st.columns(4); c[0].metric('Episodes parsed', out['episodes']); c[1].metric('Candidate windows', f"{out['candidates']:,}")
    c[2].metric('Shortlisted (rules)', out['shortlist']); c[3].metric('Judged OK', f'{len(ok)} / {len(out["judged"])}')
    if out['empty']: st.warning(f"These files parsed to zero scenes or dialogue (format variant?): {out['empty']}")
    if provider == 'mock': st.warning('Mock mode: scores are the rule-based stand-in, not a model judgement.')
    if bad: st.warning(f'{len(bad)} clips failed. First reason: {bad[0]["judge"]["problems"][:1]}')
    if ok:
        rows = []
        for i, r in enumerate(ok, 1):
            b, w = r['llm_breakdown_0_10'], r['_w']
            rows.append({'post order': i, 'episode': r['episode'], 'start': fmt(w['start']), 'end': fmt(w['end']), 'dur (s)': round(w['end'] - w['start'], 1),
                         'score /100': r['final_score_100'], 'hook': b['hook'], 'cliffhanger': b['cliffhanger'], 'standalone': b['standalone'],
                         'conflict (rule)': b['conflict(rule)'], 'pacing (rule)': b['pacing(rule)'], 'archetype': r['archetype_llm'],
                         'hook quote': r['judge']['raw']['hook']['evidence'], 'cliffhanger quote': r['judge']['raw']['cliffhanger']['evidence'], 'why it works': r['judge']['raw']['why_it_works']})
        df = pd.DataFrame(rows)
        st.subheader('Ranked promos')
        st.dataframe(df.drop(columns=['hook quote', 'cliffhanger quote', 'why it works']), use_container_width=True, hide_index=True)
        d1, d2 = st.columns(2)
        d1.download_button('Download ranked CSV', df.to_csv(index=False).encode('utf-8'), 'promos_ranked.csv', 'text/csv')
        d2.download_button('Download full JSON', json.dumps(out['judged'], indent=1).encode('utf-8'), 'judged.json', 'application/json')
        st.subheader('Details')
        for i, r in enumerate(ok[:15], 1):
            raw, b, w = r['judge']['raw'], r['llm_breakdown_0_10'], r['_w']
            with st.expander(f"#{i}  Ep {r['episode']}  {fmt(w['start'])}-{fmt(w['end'])}  |  {r['final_score_100']}/100  |  {r['archetype_llm']}", expanded=(i == 1)):
                st.write(f"**Summary:** {raw['what_happens']}")
                st.write(f"**Hook ({b['hook']}/10):** \"{raw['hook']['evidence']}\"")
                st.write(f"**Cliffhanger ({b['cliffhanger']}/10):** \"{raw['cliffhanger']['evidence']}\"  \n_Unresolved:_ {raw['cliffhanger'].get('unresolved_question') or raw['cliffhanger'].get('why', '')}")
                st.write(f"**Standalone ({b['standalone']}/10):** {raw['standalone'].get('confusions') or 'no confusions flagged'}")
                st.write(f"**Why it works:** {raw['why_it_works']}")
                st.caption(f"Archetype: {r['archetype_meaning']} | Rule-based archetype was: {r['archetype']} | Score = hook 25 + cliffhanger 30 + standalone 20 (model) + conflict 15 + pacing 10 (rules)")
    st.caption('Limits: reads text only (no acting, visuals or music); clips judged by the model are only the shortlisted ones; always have an editor review before posting.')
