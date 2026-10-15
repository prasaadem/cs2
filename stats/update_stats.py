#!/usr/bin/env python3
"""Merge games parsed from a folder of server logs into the permanent JSON archive.

Usage:
    python stats/update_stats.py --logs PATH [--data data/games]

Rules, so history is never lost:
  * a game not in the archive is added as data/games/<id>.json
  * a completed game already in the archive is never changed
  * an unfinished game is replaced only by a version with more rounds
  * a game is re-parsed by a newer parser version only from logs that are at
    least as complete (same or more rounds, and finished if it was finished)
  * nothing is ever deleted (games missing from the logs stay as they are)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import logparse  # noqa: E402


def load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def save(path, game):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(game, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write('\n')
    os.replace(tmp, path)


def merge(games, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    added, updated = [], []
    for g in games:
        path = os.path.join(data_dir, g['id'] + '.json')
        if not os.path.exists(path):
            save(path, g)
            added.append(g)
            continue
        old = load(path)
        more_rounds = len(g['rounds']) > len(old.get('rounds', ''))
        # a newer parser may re-parse a game, but only from logs at least as complete
        upgrade = (g.get('v', 0) > old.get('v', 0) and len(g['rounds']) >= len(old.get('rounds', ''))
                   and (g['fin'] or not old.get('fin')))
        if upgrade or (not old.get('fin') and (g['fin'] or more_rounds)):
            save(path, g)
            updated.append(g)
    return added, updated


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--logs', required=True, help='folder containing the server .log files')
    ap.add_argument('--data', default=os.path.join(HERE, '..', 'data', 'games'))
    ap.add_argument('--min-rounds', type=int, default=3, help='skip matches with fewer rounds (default 3)')
    args = ap.parse_args()

    games = logparse.parse_logs(args.logs, args.min_rounds)
    added, updated = merge(games, args.data)
    total = len([f for f in os.listdir(args.data) if f.endswith('.json')])
    print(f'parsed {len(games)} games from logs: {len(added)} new, {len(updated)} updated; archive has {total} games')
    for g in added:
        print(f'  + {g["id"]}  {g["ct"]}:{g["t"]}{"" if g["fin"] else " (unfinished)"}')
    for g in updated:
        print(f'  ~ {g["id"]}  {g["ct"]}:{g["t"]}{"" if g["fin"] else " (unfinished)"}')

    # one-line summary for the commit message
    nights = sorted({g['night'] for g in added + updated})
    summary = f'+{len(added)} games' + (f', {len(updated)} updated' if updated else '') + (f' ({", ".join(nights)})' if nights else '')
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a', encoding='utf-8') as fh:
            fh.write(f'summary={summary}\nchanged={"true" if added or updated else "false"}\n')


if __name__ == '__main__':
    main()
