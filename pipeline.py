"""Pipeline wrapper used by the Streamlit app (no Streamlit imports, so it is testable on its own)."""
import io, json, os, tempfile, threading, zipfile, sys
APP_DIR = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, APP_DIR)
from parse import load_all, empty_episodes
import score_and_tag, judge
LOCK = threading.Lock()   # the stages use relative paths, so run one job at a time

def run_pipeline(files, provider, model, key, n_clips, only_eps=None, delay=7, progress=None):
    """files: list of (filename, bytes) - .txt episodes and/or .zip of them."""
    work = tempfile.mkdtemp(prefix='promo_'); epdir = os.path.join(work, 'episodes'); os.makedirs(epdir)
    for name, data in files:
        if name.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if n.lower().endswith('.txt') and '__MACOSX' not in n:
                        open(os.path.join(epdir, os.path.basename(n)), 'wb').write(z.read(n))
        elif name.lower().endswith('.txt'):
            open(os.path.join(epdir, os.path.basename(name)), 'wb').write(data)
    eps = load_all(epdir)                       # exits with a message if nothing looks like an episode
    cfg = json.load(open(os.path.join(APP_DIR, 'config.json')))
    cfg['provider'] = provider; cfg['request_delay_s'] = delay
    if provider != 'mock': cfg['providers'][provider]['model'] = model
    with LOCK:
        old = os.getcwd(); os.chdir(work)
        try:
            json.dump(eps, open('parsed.json', 'w')); json.dump(cfg, open('config.json', 'w'))
            if provider != 'mock':
                env = cfg['providers'][provider]['api_key_env']
                if key: os.environ[env] = key
            shortlist, nraw, nvalid = score_and_tag.run()
            judged = judge.run(provider, limit=n_clips, only_eps=only_eps, progress=progress)
        finally:
            os.chdir(old)
    return {'episodes': len(eps), 'empty': empty_episodes(eps), 'candidates': nraw, 'shortlist': len(shortlist), 'judged': judged}

def rank(judged):
    ok = [r for r in judged if r['judge']['valid']]
    for r in ok: r['_w'] = r['trimmed'] if r.get('trim_ok') else r['segments'][0]
    ok.sort(key=lambda r: -r['final_score_100']); return ok
