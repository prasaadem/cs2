#!/usr/bin/env python3
"""Build the GitHub Pages site from the JSON archive.

Usage:
    python stats/build_site.py [--data data/games] [--docs docs] [--title "CS2 Nights"]

Pass --mark-synced after a successful DatHost download to record the sync time;
without it the previous sync time is kept.

Writes docs/data/games.json (all games in one file, oldest first),
docs/data/positions.json (kill and grenade positions, loaded only by the
heatmap page) and docs/index.html (the page, which loads that JSON).
"""
import argparse
import datetime as dt
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def radar_overviews(radar_dir):
    """Read the game's overview files (docs/radar/<map>.txt) for maps that also have
    docs/radar/<map>.png, giving the numbers that place world positions on the image."""
    out = {}
    for txt in glob.glob(os.path.join(radar_dir, '*.txt')):
        name = os.path.splitext(os.path.basename(txt))[0]
        if not os.path.exists(os.path.join(radar_dir, name + '.png')):
            continue
        with open(txt, encoding='utf-8', errors='replace') as fh:
            body = fh.read()
        vals = {}
        for key in ('pos_x', 'pos_y', 'scale'):
            m = re.search(r'"%s"\s+"(-?[\d.]+)"' % key, body)
            if m:
                vals[key] = float(m.group(1))
        if len(vals) == 3:
            out[name] = vals
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default=os.path.join(HERE, '..', 'data', 'games'))
    ap.add_argument('--docs', default=os.path.join(HERE, '..', 'docs'))
    ap.add_argument('--template', default=os.path.join(HERE, 'template.html'))
    ap.add_argument('--title', default='CS2 Nights')
    ap.add_argument('--mark-synced', action='store_true', help='record now as the last DatHost sync time')
    args = ap.parse_args()

    games = []
    for f in glob.glob(os.path.join(args.data, '*.json')):
        with open(f, encoding='utf-8') as fh:
            games.append(json.load(fh))
    games.sort(key=lambda g: g['start_utc'])
    updated = max((g['start_utc'] for g in games), default='')

    out = os.path.join(args.docs, 'data', 'games.json')
    synced = None
    if args.mark_synced:
        synced = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    elif os.path.exists(out):
        with open(out, encoding='utf-8') as fh:
            synced = json.load(fh).get('synced')

    os.makedirs(os.path.join(args.docs, 'data'), exist_ok=True)
    positions = {}
    for g in games:
        kp, np_ = g.pop('kp', None), g.pop('np', None)
        if kp is not None or np_ is not None:
            positions[g['id']] = [kp or [], np_ or []]
    with open(os.path.join(args.docs, 'data', 'positions.json'), 'w', encoding='utf-8') as fh:
        json.dump(positions, fh, separators=(',', ':'))
    payload = {'title': args.title, 'updated': updated, 'synced': synced, 'games': games}
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(',', ':'))

    radar_dir = os.path.join(args.docs, 'radar')
    radar = radar_overviews(radar_dir) if os.path.isdir(radar_dir) else {}
    if os.path.isdir(radar_dir):
        with open(os.path.join(radar_dir, 'overviews.json'), 'w', encoding='utf-8') as fh:
            json.dump(radar, fh, indent=1, sort_keys=True)

    with open(args.template, encoding='utf-8') as fh:
        html = fh.read().replace('__TITLE__', args.title)
    with open(os.path.join(args.docs, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write(html)

    nights = {g['night'] for g in games}
    print(f'site: {len(games)} games over {len(nights)} nights, radar images for {len(radar)} maps'
          f' -> {os.path.abspath(args.docs)}')


if __name__ == '__main__':
    main()
