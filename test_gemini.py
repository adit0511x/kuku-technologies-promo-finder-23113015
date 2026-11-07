"""Check your key + model. Usage:  python test_gemini.py            (uses model from config.json)
                                  python test_gemini.py MODEL_NAME  (try another model)
Step 1 lists the Flash models your key can use (fast call). Step 2 sends one tiny message (waits up to 90s)."""
import json, os, sys, time, urllib.request, urllib.error
if os.path.exists('.env'):
    for ln in open('.env', encoding='utf-8'):
        ln = ln.strip()
        if ln and not ln.startswith('#') and '=' in ln:
            k, v = ln.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
cfg = json.load(open('config.json'))['providers']['gemini']
key = os.environ.get(cfg['api_key_env'])
if not key: sys.exit('No GEMINI_API_KEY found. Check your .env file is in this folder and named exactly .env')
model = (sys.argv[1] if len(sys.argv) > 1 else cfg['model']).replace('models/', '')
H = {"Content-Type": "application/json", "x-goog-api-key": key}
print('key loaded (length', len(key), ')')

print('\nStep 1: models your key can use ...')
t = time.time()
try:
    r = json.load(urllib.request.urlopen(urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers=H), timeout=20))
    names = [m['name'].replace('models/', '') for m in r.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
    flash = [n for n in names if 'flash' in n]
    print(f'  reached Google in {time.time()-t:.1f}s. {len(names)} text models; flash ones:'); [print('   ', n) for n in flash[:15]]
except urllib.error.HTTPError as e:
    print('  HTTP', e.code, e.read().decode('utf-8', 'ignore')[:300])
except Exception as e:
    print('  could NOT reach Google in 20s:', repr(e)[:150], '\n  -> network problem. Try a phone hotspot or turn VPN/proxy off.'); sys.exit()

print(f'\nStep 2: asking {model} to say "ready" (up to 90s) ...')
body = {"contents": [{"parts": [{"text": "Reply with the single word: ready"}]}]}
t = time.time()
try:
    r = json.load(urllib.request.urlopen(urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", json.dumps(body).encode(), H), timeout=90))
    print(f"  OK in {time.time()-t:.1f}s:", r['candidates'][0]['content']['parts'][0]['text'].strip()[:80])
except urllib.error.HTTPError as e:
    print('  HTTP', e.code, e.read().decode('utf-8', 'ignore')[:300])
except Exception as e:
    print(f'  no answer after {round(time.time()-t)}s:', repr(e)[:150], '\n  -> model is too slow/overloaded. Re-run with a model from the flash list above, e.g.  python test_gemini.py <name>')
