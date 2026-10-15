#!/usr/bin/env python3
"""Download the server's logs/ folder from the DatHost API.

Usage:
    python stats/fetch_dathost.py --out DIR

Credentials come from environment variables (GitHub Actions secrets):
    DATHOST_EMAIL, DATHOST_PASSWORD   DatHost login (HTTP basic auth)
    DATHOST_SERVER_ID                 id from the control panel URL
    DATHOST_ACCOUNT_EMAIL             optional: act on an account this login was invited to

Steps: ask DatHost to sync the server's files to its cache, wait, then download
the logs directory (DatHost returns a directory as a zip) and extract the .log files.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

API = os.environ.get('DATHOST_API', 'https://dathost.com/api/0.1')


def env(name, required=True):
    v = os.environ.get(name, '').strip()
    if required and not v:
        sys.exit(f'error: environment variable {name} is not set')
    return v


def request(method, path, retries=3, timeout=300):
    auth = base64.b64encode(f'{env("DATHOST_EMAIL")}:{env("DATHOST_PASSWORD")}'.encode()).decode()
    headers = {'Authorization': 'Basic ' + auth, 'User-Agent': 'cs2-stats'}
    account = env('DATHOST_ACCOUNT_EMAIL', required=False)
    if account:
        headers['Account-Email'] = account
    url = API + path
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, method=method, headers=headers, data=b'' if method == 'POST' else None)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f'error: DatHost rejected the login (HTTP {e.code}); check DATHOST_EMAIL / DATHOST_PASSWORD'
                         ' / DATHOST_ACCOUNT_EMAIL')
            # 4xx won't improve with retries (bad credentials, wrong server id, missing file)
            if e.code < 500 or attempt == retries:
                raise RuntimeError(f'{method} {path} -> HTTP {e.code} {e.reason}') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries:
                raise RuntimeError(f'{method} {path} -> {e}') from None
        wait = 15 * attempt
        print(f'  {method} {path} failed (attempt {attempt}), retrying in {wait}s')
        time.sleep(wait)


def extract_logs(blob, out):
    n = 0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            name = os.path.basename(info.filename)  # flatten; never trust paths inside the zip
            if info.is_dir() or not name.endswith('.log'):
                continue
            with z.open(info) as src, open(os.path.join(out, name), 'wb') as dst:
                dst.write(src.read())
            n += 1
    return n


def list_log_paths(server):
    """Fallback: list logs/ and return file paths. The response shape isn't documented,
    so accept a list of strings or of objects with a path/name field."""
    raw = json.loads(request('GET', f'/game-servers/{server}/files?path=logs&max_depth=1'))
    items = raw if isinstance(raw, list) else raw.get('files', [])
    paths = []
    for it in items:
        p = it if isinstance(it, str) else (it.get('path') or it.get('name') or '')
        if p.endswith('.log'):
            paths.append(p if p.startswith('logs/') else 'logs/' + p.lstrip('/'))
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='folder to write the .log files into')
    ap.add_argument('--wait', type=int, default=60, help='seconds to wait after sync-files (default 60)')
    args = ap.parse_args()
    server = urllib.parse.quote(env('DATHOST_SERVER_ID'), safe='')
    os.makedirs(args.out, exist_ok=True)

    print('syncing server files to the DatHost cache')
    try:
        request('POST', f'/game-servers/{server}/sync-files')
        time.sleep(args.wait)
    except RuntimeError as e:
        # a stopped server was already synced when it shut down, so carry on
        print(f'  warning: {e}; using the cached files')

    print('downloading logs/')
    try:
        blob = request('GET', f'/game-servers/{server}/files/logs')
        if not blob.startswith(b'PK'):
            raise RuntimeError('logs/ download was not a zip')
        n = extract_logs(blob, args.out)
    except RuntimeError as e:
        print(f'  zip download failed ({e}); downloading files one by one')
        n = 0
        for p in list_log_paths(server):
            data = request('GET', f'/game-servers/{server}/files/' + urllib.parse.quote(p))
            with open(os.path.join(args.out, os.path.basename(p)), 'wb') as fh:
                fh.write(data)
            n += 1
    if n == 0:
        sys.exit('error: no .log files downloaded')
    print(f'downloaded {n} log files to {args.out}')


if __name__ == '__main__':
    main()
