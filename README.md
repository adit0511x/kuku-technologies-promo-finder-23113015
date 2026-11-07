# Promo Finder: find 20-60s promo clips in microdrama screenplays

Reads timestamped screenplays, finds promo windows (hook, cliffhanger, makes sense alone), tags an archetype, scores (0-100 with breakdown) and ranks them.
The confidential episode pack is NOT in this repo: upload your own episode .txt files (or one .zip).

## Streamlit app
    pip install -r requirements.txt
    streamlit run app.py
Upload episodes, pick a provider (gemini / openrouter / mock), paste an API key in the sidebar (used for the run only, never stored), click Find promos, download CSV/JSON.
`mock` runs the whole pipeline with rule-based stand-in scores (pipeline test only, not a judgement).
Deploy: push this folder to GitHub, then share.streamlit.io -> New app -> main file `app.py`. Do not put your own key in Secrets on a public app (strangers could spend your quota).

## Command line
1. Copy `.env.example` to `.env`, add `GEMINI_API_KEY=...` (never commit it).
2. `python parse.py "path/to/episodes"`  -> parsed.json (warns if an episode parses empty)
3. `python score_and_tag.py`  -> stage1_promos.json/.csv (candidates, validation, rule scores, archetype)
4. `python test_gemini.py`  -> lists models your key can use (names change; set one in config.json)
5. `python judge.py --provider gemini [--limit N] [--episodes 5,14,22]`  -> stage2_gemini.json (cached, resumable, paced, stops on repeated 429)
6. `python make_report.py stage2_gemini.json` -> promos_ranked.csv, promos_top15.md, failures_auto.md
7. `python eval.py stage2_gemini.json` -> agreement with human blind picks (my_picks.json, not in repo)

## Design
Code: tolerant parser, 23k candidate windows (start on a line/shot, end on a spoken line), validation, rule scores, caching.
LLM: sees only the clip text; returns hook/cliffhanger/standalone scores with exact quotes, archetype, and trim as line numbers. Guards: model never writes timestamps; quotes must appear verbatim in the clip; archetype from a fixed list; trim re-checked to 20-60s. Model is swappable in config.json.
Human: editor reviews failures_auto.md; blind hand-picked segments are the test set.

## Known limits
Text only (no acting/visuals/music). Rule scores are punctuation proxies. Max 2 windows per episode and no episode-opening rule (two of my picks were missed). No cross-episode stitching. Free-tier quota limited my run to 15 of 99 clips. Single run, stability untested.
