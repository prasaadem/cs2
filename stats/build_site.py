#!/usr/bin/env python3
"""Build the GitHub Pages site from the JSON archive.

Usage:
    python stats/build_site.py [--data data/games] [--docs docs] [--title "CS2 Nights"]

Writes docs/data/games.json (all games in one file, oldest first) and
docs/index.html (the page, which loads that JSON).
"""
import argparse
import datetime as dt
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default=os.path.join(HERE, '..', 'data', 'games'))
    ap.add_argument('--docs', default=os.path.join(HERE, '..', 'docs'))
    ap.add_argument('--template', default=os.path.join(HERE, 'template.html'))
    ap.add_argument('--title', default='CS2 Nights')
    args = ap.parse_args()

    games = []
    for f in glob.glob(os.path.join(args.data, '*.json')):
        with open(f, encoding='utf-8') as fh:
            games.append(json.load(fh))
    games.sort(key=lambda g: g['start_utc'])
    updated = max((g['start_utc'] for g in games), default='')

    os.makedirs(os.path.join(args.docs, 'data'), exist_ok=True)
    payload = {'title': args.title, 'updated': updated, 'games': games}
    with open(os.path.join(args.docs, 'data', 'games.json'), 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(',', ':'))

    with open(args.template, encoding='utf-8') as fh:
        html = fh.read().replace('__TITLE__', args.title)
    with open(os.path.join(args.docs, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write(html)

    nights = {g['night'] for g in games}
    print(f'site: {len(games)} games over {len(nights)} nights -> {os.path.abspath(args.docs)}')


if __name__ == '__main__':
    main()
