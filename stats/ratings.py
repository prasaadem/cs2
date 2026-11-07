#!/usr/bin/env python3
"""Compute player ratings for the team balancer from the permanent game archive.

Usage:
    python stats/ratings.py --out ratings.json [--data data/games]
    python stats/ratings.py --out ratings.json --publish     # also PUT it to the Worker

The output is NOT written under docs/ or data/ on purpose: those folders are
public, and the ratings are only meant to be used by the Worker, never shown.

Model (settings chosen by walk-forward backtest over the archive):
  * performance rating: damage per round, kill-death difference and entry
    kills-minus-deaths per round, averaged over a player's games with an
    exponential recency decay (half-life 20 games), pulled toward the group
    average until a player has about 8 games' worth of data
  * win/loss rating: an Elo-style number updated from each team's share of
    rounds won
  * final rating: an even blend of the two, each in standard-deviation units
    across all known players (0 is average, +1 is one spread above)

Publishing reads RATINGS_PUBLISH_URL and RATINGS_TOKEN from the environment.
"""
import argparse
import glob
import json
import math
import os
import statistics
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

SCHEMA = 1
MIN_ROUNDS = 5       # a player needs this many rounds in a game for it to count
PRIOR_GAMES = 8      # games' worth of pull toward the group average
HALF_LIFE = 20       # games until a game counts half as much
BLEND = 0.5          # weight of the performance rating (rest is win/loss)
ELO_K = 0.24         # learning rate of the win/loss rating
PERF_WEIGHTS = {'adr': 1.0, 'kd': 2.0, 'entry': 3.0}
REGULAR_MIN_GAMES = 10
PROVISIONAL_BELOW = 5


def num(p, key):
    return p.get(key) or 0


def load_games(data_dir):
    """Finished games with a winner, oldest first (ids start with the UTC start time)."""
    games = []
    for path in sorted(glob.glob(os.path.join(data_dir, '*.json'))):
        with open(path, encoding='utf-8') as fh:
            g = json.load(fh)
        if g.get('fin') and g.get('win'):
            games.append(g)
    return games


def team_results(game):
    """{team: {'players': [...], 'share': fraction of rounds won}} or None if unusable."""
    rounds = game['rounds']
    teams = defaultdict(list)
    for p in game['p']:
        if num(p, 'r') < MIN_ROUNDS:
            continue
        won = lost = 0
        for i, side in enumerate(p['sd']):
            if side == '.' or i >= len(rounds):
                continue
            if rounds[i] == side:
                won += 1
            else:
                lost += 1
        teams[p['team']].append((p, won, lost))
    if len(teams) != 2 or any(len(v) < 2 for v in teams.values()):
        return None
    out = {}
    for team, rows in teams.items():
        won = statistics.mean(w for _, w, _ in rows)
        lost = statistics.mean(l for _, _, l in rows)
        out[team] = {'players': [p for p, _, _ in rows], 'share': won / (won + lost) if won + lost else 0.5}
    return out


def performance(p):
    r = num(p, 'r')
    adr = num(p, 'dmg') / r
    kd = (num(p, 'k') - num(p, 'd')) / r
    entry = (num(p, 'ek') - num(p, 'ed')) / r
    w = PERF_WEIGHTS
    return w['adr'] * adr / 75 + w['kd'] * kd + w['entry'] * entry


def compute(games):
    """Run through the archive oldest to newest and return the rating table."""
    hist = defaultdict(list)       # id -> [(game index, performance)]
    elo = defaultdict(float)
    names, last_night, played = {}, {}, defaultdict(int)
    n = 0
    for game in games:
        res = team_results(game)
        if res is None:
            continue
        a, b = list(res.values())
        ea = statistics.mean(elo[p['id']] for p in a['players'])
        eb = statistics.mean(elo[p['id']] for p in b['players'])
        expected = 1 / (1 + math.exp(-(ea - eb)))
        for p in a['players']:
            elo[p['id']] += ELO_K * (a['share'] - expected)
        for p in b['players']:
            elo[p['id']] -= ELO_K * (a['share'] - expected)
        for t in res.values():
            for p in t['players']:
                hist[p['id']].append((n, performance(p)))
                names[p['id']] = p['n']
                last_night[p['id']] = game.get('night')
                played[p['id']] += 1
        n += 1

    if not hist:
        return {}
    every = [v for h in hist.values() for _, v in h]
    group_mean = statistics.mean(every)

    def perf_rating(pid):
        h = hist[pid]
        weights = [0.5 ** ((n - i) / HALF_LIFE) for i, _ in h]
        total = sum(weights)
        s = sum(w * v for w, (_, v) in zip(weights, h))
        return (group_mean * PRIOR_GAMES + s) / (PRIOR_GAMES + total)

    perf = {pid: perf_rating(pid) for pid in hist}
    p_mean, p_sd = statistics.mean(perf.values()), statistics.pstdev(perf.values()) or 1.0
    e_mean, e_sd = statistics.mean(elo[i] for i in hist), statistics.pstdev([elo[i] for i in hist]) or 1.0
    table = {}
    for pid in hist:
        rating = BLEND * (perf[pid] - p_mean) / p_sd + (1 - BLEND) * (elo[pid] - e_mean) / e_sd
        table[pid] = {
            'name': names[pid],
            'rating': round(rating, 4),
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
