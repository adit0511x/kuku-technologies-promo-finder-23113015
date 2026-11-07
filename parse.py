import re, glob, os, sys, json
from collections import Counter

T = r'(\d+):(\d+\.\d+)'
def ts(m, s): return int(m)*60 + float(s)

BLOCK_RE = re.compile(r'^\*\*(.+?):\*\*\s*$')
TIME_RE = re.compile(r'^Start:\s*\((\d+):(\d+\.\d+)\)\s*\|\s*End:\s*\((\d+):(\d+\.\d+)\)')

def parse_episode(path):
    txt = open(path, encoding='utf-8').read()
    ep = {'file': os.path.basename(path)}
    m = re.search(r'EPISODE NUMBER:\s*Episode\s*(\d+)', txt); ep['num'] = int(m.group(1)) if m else None
    m = re.search(r'EPISODE LOGLINE:\s*(.+)', txt); ep['logline'] = m.group(1).strip() if m else ''
    m = re.search(r'CONTINUITY NOTES:\s*(.+)', txt); ep['continuity'] = m.group(1).strip() if m else ''
    body = txt.split('--- SCRIPT START ---')[-1].split('--- SCRIPT END ---')[0]
    scenes = []
    for chunk in re.split(r'\n(?=SCENE \d+\n)', body.strip()):
        mh = re.match(r'SCENE (\d+)\nScene heading:\s*(.+)\nScene start:\s*(\d+):(\d+\.\d+)\nScene end:\s*(\d+):(\d+\.\d+)', chunk, re.I)
        if not mh: continue
        sc = {'scene': int(mh.group(1)), 'heading': mh.group(2).strip(),
              'start': ts(mh.group(3), mh.group(4)), 'end': ts(mh.group(5), mh.group(6)), 'events': []}
        lines = chunk.split('\n'); i = 0
        while i < len(lines):
            b = BLOCK_RE.match(lines[i].strip())
            if b and i+1 < len(lines):
                t = TIME_RE.match(lines[i+1].strip())
                if t:
                    text = []; j = i+2
                    while j < len(lines) and not BLOCK_RE.match(lines[j].strip()) and not lines[j].startswith('SCENE '):
                        if lines[j].strip(): text.append(lines[j].strip())
                        j += 1
                    label = b.group(1)
                    kind = label.split(' (')[0].strip()
                    typ = kind if kind in ('CAMERA','ACTION','SOUND FX','MUSIC','SFX') else 'DIALOGUE'
                    sc['events'].append({'type': typ, 'speaker': kind if typ=='DIALOGUE' else None,
                        'tone': (re.search(r'\((.*)\)', label).group(1) if '(' in label else None),
                        'start': ts(t.group(1), t.group(2)), 'end': ts(t.group(3), t.group(4)),
                        'text': ' '.join(text)})
                    i = j; continue
            i += 1
        scenes.append(sc)
    ep['scenes'] = scenes
    ep['duration'] = max((s['end'] for s in scenes), default=0)
    return ep

def empty_episodes(eps):
    """Episodes that parsed to nothing (usually a format variant). Surface these loudly."""
    return [e['file'] for e in eps if not e['scenes'] or not any(ev['type'] == 'DIALOGUE' for s in e['scenes'] for ev in s['events'])]

def load_all(folder):
    paths = [p for p in sorted(glob.glob(os.path.join(folder, '*.txt')))
             if 'SCRIPT START' in open(p, encoding='utf-8', errors='ignore').read()]   # skip non-episode .txt files
    if not paths: sys.exit(f'No episode .txt files found in: {os.path.abspath(folder)}')
    return [parse_episode(p) for p in paths]

if __name__ == '__main__':
    eps = load_all(sys.argv[1] if len(sys.argv) > 1 else '.')   # default: current folder
    print('episodes', len(eps), 'scenes', sum(len(e['scenes']) for e in eps))
    types = Counter(ev['type'] for e in eps for s in e['scenes'] for ev in s['events'])
    print(types)
    durs = [e['duration'] for e in eps]
    print('ep duration min/avg/max', min(durs), sum(durs)/len(durs), max(durs))
    print('scenes/ep', Counter(len(e['scenes']) for e in eps))
    # integrity checks
    bad = 0
    for e in eps:
        for s in e['scenes']:
            for ev in s['events']:
                if ev['end'] < ev['start'] or ev['end'] > s['end']+0.6 or ev['start'] < s['start']-0.1: bad += 1
    print('events outside scene bounds / inverted:', bad)
    spk = Counter(ev['speaker'] for e in eps for s in e['scenes'] for ev in s['events'] if ev['type']=='DIALOGUE')
    print(len(spk), 'distinct speaker labels'); print(spk.most_common(40))
    nodlg = [e['num'] for e in eps if not any(ev['type']=='DIALOGUE' for s in e['scenes'] for ev in s['events'])]
    print('no dialogue eps', nodlg)
    json.dump(eps, open('parsed.json','w'))
    bad = empty_episodes(eps)
    if bad: print('WARNING: parsed to zero scenes/dialogue (check format):', bad)
    print('wrote parsed.json')
