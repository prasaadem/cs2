#!/usr/bin/env python3
"""Post a summary of newly synced games to a Discord channel.

Usage:
    python stats/notify_discord.py --changes changes.json [--wait-for-site] [--dry-run]

Needs DISCORD_WEBHOOK_URL in the environment (a GitHub Actions secret).
changes.json is written by update_stats.py --changes. Nothing is sent when it
lists no games. With --wait-for-site the script first waits (up to 6 minutes)
until GitHub Pages serves the new data, so the link shows the update.
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from logparse import rating  # noqa: E402

DATA = os.path.join(HERE, '..', 'data', 'games')
EMBED_COLOR = 0xF0B232  # the site's accent amber
MIN_SHARE = 0.5         # night MVP must have played half the night's games


def site_url():
    url = os.environ.get('SITE_URL')
    if url:
        return url.rstrip('/') + '/'
    repo = os.environ.get('GITHUB_REPOSITORY', 'prasaadem/cs2')
    owner, name = repo.split('/', 1)
    return f'https://{owner.lower()}.github.io/{name}/'


def map_name(m):
    for p in ('de_', 'cs_', 'aim_', 'fy_', 'ar_', 'dz_'):
        if m.startswith(p):
            m = m[len(p):]
            break
    return m.replace('_', ' ').title()


def night_label(n):
    d = dt.date.fromisoformat(n)
    return f'{d:%a}, {d:%b} {d.day}'


_cache = {}


def load(gid):
    """Read one archived game, with its MVP marked (cached)."""
    if gid not in _cache:
        with open(os.path.join(DATA, gid + '.json'), encoding='utf-8') as fh:
            g = json.load(fh)
        mark_mvp(g)
        _cache[gid] = g
    return _cache[gid]


def night_leaders(games):
    """Night MVP by rating over the night's games (min. half of them), and most kills."""
    tot = collections.defaultdict(collections.Counter)
    names = {}
    for g in games:
        for p in g['p']:
            names[p['id']] = p['n']
            t = tot[p['id']]
            t['g'] += 1
            for k in ('k', 'd', 'r', 'k1', 'k2', 'k3', 'k4', 'k5'):
                t[k] += p.get(k, 0)
    rows = []
    for pid, t in tot.items():
        mk = {i: t['k%d' % i] for i in range(1, 6)}
        rows.append({'n': names[pid], 'g': t['g'], 'k': t['k'], 'd': t['d'], 'rt': rating(t['k'], t['d'], t['r'], mk)})
    elig = [r for r in rows if r['g'] >= max(1, len(games) * MIN_SHARE)] or rows
    mvp = max(elig, key=lambda r: r['rt'])
    top = max(rows, key=lambda r: (r['k'], r['rt']))
    return mvp, top


def game_line(g, prefix=''):
    score = f'{g["ct"]}:{g["t"]}'
    mvp = next((p for p in g['p'] if p['id'] == g.get('mvp')), None) or g['p'][0]
    flag = '' if g['fin'] else ' *(unfinished)*'
    return f'{prefix}**{map_name(g["map"])}** {score}{flag} · ⭐ {mvp["n"]} {mvp["k"]}–{mvp["d"]}'


def build_embeds(changes):
    added = [load(i) for i in changes.get('added', [])]
    updated = [load(i) for i in changes.get('updated', [])]
    by_night = collections.defaultdict(lambda: {'added': [], 'updated': []})
    for g in added:
        by_night[g['night']]['added'].append(g)
    for g in updated:
        by_night[g['night']]['updated'].append(g)

    base = site_url()
    embeds = []
    for night in sorted(by_night)[-10:]:  # Discord allows 10 embeds per message
        ch = by_night[night]
        new, upd = sorted(ch['added'], key=lambda g: g['start_utc']), ch['updated']
        lines = [game_line(g) for g in new]
        lines += [game_line(g, '✅ completed: ') for g in upd]
        night_games = [g for g in (load(f[:-5]) for f in os.listdir(DATA) if f.endswith('.json'))
                       if g['night'] == night]
        mvp, top = night_leaders(night_games)
        title = f'{night_label(night)}: {len(new)} new game{"s" if len(new) != 1 else ""}' if new \
            else f'{night_label(night)}: {len(upd)} game{"s" if len(upd) != 1 else ""} updated'
        embeds.append({
            'title': title,
            'url': f'{base}#/night/{night}',
            'color': EMBED_COLOR,
            'description': '\n'.join(lines)[:3800],
            'fields': [
                {'name': '🏆 Night MVP', 'value': f'{mvp["n"]} · {mvp["rt"]:.2f} rating', 'inline': True},
                {'name': '🔫 Most kills', 'value': f'{top["n"]} · {top["k"]}', 'inline': True},
                {'name': 'Night so far', 'value': f'{len(night_games)} games', 'inline': True},
            ],
        })
    return embeds


def mark_mvp(g):
    """Same rule as the site: best rating among players with half the rounds."""
    elig = [p for p in g['p'] if p['r'] >= len(g['rounds']) * MIN_SHARE] or g['p']
    g['mvp'] = max(elig, key=lambda p: p['rt'])['id']


def wait_for_site(ids, timeout=360):
    url = site_url() + 'data/games.json'
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f'{url}?t={int(time.time())}', headers={'Cache-Control': 'no-cache'})
            with urllib.request.urlopen(req, timeout=30) as r:
                live = {g['id'] for g in json.load(r)['games']}
            if set(ids) <= live:
                print('site is serving the new data')
                return
        except (urllib.error.URLError, ValueError, KeyError) as e:
            print(f'  site check failed: {e}')
        time.sleep(20)
    print('site not updated yet after waiting; sending anyway')


def post(webhook, payload):
    body = json.dumps(payload).encode()
    for attempt in range(3):
        req = urllib.request.Request(webhook, data=body, method='POST',
                                     headers={'Content-Type': 'application/json', 'User-Agent': 'cs2-stats'})
        try:
            with urllib.request.urlopen(req, timeout=30):
                return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(float(json.load(e).get('retry_after', 2)) + 0.5)
                continue
            raise SystemExit(f'error: Discord returned HTTP {e.code}') from None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--changes', required=True)
    ap.add_argument('--wait-for-site', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='print the message instead of sending it')
    args = ap.parse_args()

    with open(args.changes, encoding='utf-8') as fh:
        changes = json.load(fh)
    ids = changes.get('added', []) + changes.get('updated', [])
    if not ids:
        print('no new data; not sending')
        return

    payload = {'username': 'CS2 Stats', 'embeds': build_embeds(changes), 'allowed_mentions': {'parse': []}}
    if args.dry_run:
        print(json.dumps(payload, indent=1, ensure_ascii=False))
        return
    webhook = os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
    if not webhook:
        print('DISCORD_WEBHOOK_URL not set; not sending')
        return
    if args.wait_for_site:
        wait_for_site(ids)
    post(webhook, payload)
    print(f'posted {len(payload["embeds"])} night summary(s) to Discord')


if __name__ == '__main__':
    main()
