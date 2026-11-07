#!/usr/bin/env python3
"""Compute player ratings for the team balancer from the permanent game archive.

Usage:
    python stats/ratings.py --out ratings.json [--data data/games]
    python stats/ratings.py --out ratings.json --publish     # also PUT it to the Worker

The output is NOT written under docs/ or data/ on purpose: those folders are
public, and the ratings are only meant to be used by the Worker.

Model: each player's overall rating is the same number the site shows as
"Rating" on the leaderboard: the HLTV 1.0-style rating (1.00 is average)
computed from that player's totals of kills, deaths, rounds and multi-kill
rounds across every game in the archive, all days. Every round counts equally.

Publishing reads RATINGS_PUBLISH_URL and RATINGS_TOKEN from the environment.
"""
import argparse
import glob
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

SCHEMA = 1
TOTAL_KEYS = ('r', 'k', 'd', 'k1', 'k2', 'k3', 'k4', 'k5')
REGULAR_MIN_GAMES = 10
PROVISIONAL_BELOW = 5


def load_games(data_dir):
    """Every archived game, oldest first (the site counts all of them too)."""
    games = []
    for path in sorted(glob.glob(os.path.join(data_dir, '*.json'))):
        with open(path, encoding='utf-8') as fh:
            games.append(json.load(fh))
    return games


def hltv_rating(t):
    """Same formula as rating() in stats/template.html."""
    r = t['r']
    if not r:
        return 0.0
    return (t['k'] / r / 0.679
            + 0.7 * max(r - t['d'], 0) / r / 0.317
            + (t['k1'] + 4 * t['k2'] + 9 * t['k3'] + 16 * t['k4'] + 25 * t['k5']) / r / 1.277) / 2.7


def compute(games):
    """{player id: {name, rating, games, ...}} from career totals over all games."""
    totals, names, last_night, played = {}, {}, {}, {}
    for game in games:
        for p in game.get('p', []):
            pid = p['id']
            t = totals.setdefault(pid, dict.fromkeys(TOTAL_KEYS, 0))
            for k in TOTAL_KEYS:
                t[k] += p.get(k) or 0
            names[pid] = p['n']
            last_night[pid] = game.get('night')
            played[pid] = played.get(pid, 0) + 1
    table = {}
    for pid, t in totals.items():
        if not t['r']:
            continue
        table[pid] = {
            'name': names[pid],
            'rating': round(hltv_rating(t), 4),
            'games': played[pid],
            'last_night': last_night[pid],
            'regular': played[pid] >= REGULAR_MIN_GAMES,
            'provisional': played[pid] < PROVISIONAL_BELOW,
        }
    return table


def build(data_dir):
    games = load_games(data_dir)
    return {
        'v': SCHEMA,
        'generated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'games': len(games),
        'players': compute(games),
    }


def publish(payload):
    url = os.environ.get('RATINGS_PUBLISH_URL')
    token = os.environ.get('RATINGS_TOKEN')
    if not url or not token:
        sys.exit('publish needs RATINGS_PUBLISH_URL and RATINGS_TOKEN in the environment')
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='PUT', headers={
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
        'User-Agent': 'cs2-nights-ratings/1',   # Cloudflare rejects the default Python agent
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f'published {len(body)} bytes: HTTP {resp.status}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default=os.path.join(HERE, '..', 'data', 'games'))
    ap.add_argument('--out', required=True, help='where to write the ratings JSON (keep it out of docs/ and data/)')
    ap.add_argument('--publish', action='store_true', help='also PUT the ratings to the Worker')
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    for public in ('docs', 'data'):
        if os.path.commonpath([out, os.path.abspath(os.path.join(HERE, '..', public))]) == os.path.abspath(os.path.join(HERE, '..', public)):
            sys.exit(f'refusing to write ratings under {public}/ because that folder is public')

    payload = build(args.data)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write('\n')
    regulars = [p for p in payload['players'].values() if p['regular']]
    print(f'rated {len(payload["players"])} players ({len(regulars)} regulars) from {payload["games"]} games -> {out}')
    if args.publish:
        publish(payload)


if __name__ == '__main__':
    main()
