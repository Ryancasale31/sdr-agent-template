import json, base64, requests, sys

TOKEN  = open('.env').read().split('GITHUB_TOKEN=')[1].split()[0].strip()
REPO   = 'Ryancasale31/sdr-agent-template'
HDR    = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

def gh_push(fpath, branch, message):
    content = open(fpath, encoding='utf-8').read()
    r = requests.get(f'https://api.github.com/repos/{REPO}/contents/{fpath}',
                     params={'ref': branch}, headers=HDR, timeout=15)
    sha = r.json().get('sha') if r.status_code == 200 else None
    body = {'message': message, 'content': base64.b64encode(content.encode()).decode(), 'branch': branch}
    if sha: body['sha'] = sha
    r = requests.put(f'https://api.github.com/repos/{REPO}/contents/{fpath}',
                     json=body, headers=HDR, timeout=15)
    return 'OK' if r.status_code in (200, 201) else f'FAILED ({r.status_code}): {r.text[:100]}'

# Push data files to data branch (pipeline.json managed by radar directly -- do NOT push here)
for fpath in ['events/b2b-online-atlanta/icp_summary.json']:
    print(f'[data] {fpath}: {gh_push(fpath, "data", f"B2B Atlanta data: {fpath}")}')

# Push code files to main branch (check which branch the app uses)
for fpath in ['app.py', 'seamless_utils.py', 'radar.py', 'events_registry.py', 'storage.py', 'icp_profile.py', 'event_setup.py']:
    # Try main branch first, then master
    for branch in ['main', 'master']:
        result = gh_push(fpath, branch, f'B2B Atlanta: update {fpath}')
        if 'OK' in result:
            print(f'[{branch}] {fpath}: {result}')
            break
        elif '422' in result or '404' in result:
            continue
        else:
            print(f'[{branch}] {fpath}: {result}')
            break

print('\nDone.')
