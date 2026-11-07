#!/usr/bin/env python3
""""Last night's grudges": nemesis, rivalries and streak duos from the most recent
game night only. Posted by the Discord bot after /server start.

Rules:
  * Only the most recent night in the archive counts, however long ago it was.
  * Warm-up maps (aim_*, awp_*) are skipped.
  * Nemesis: the opponent who killed you most that night (at least 3 kills).
    Two players who are each other's nemesis share one line.
  * Rivalries: the three pairs with the most kills on each other.
  * Duos: pairs on the same team in 3+ finished games who won all or lost all.

Usage: python stats/recap.py [--data data/games]     # prints the message
"""
import argparse
import glob
import itertools
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))

WARMUP_PREFIXES = ('aim_', 'awp_')
MIN_ROUNDS = 5
NEMESIS_MIN_KILLS = 3
DUO_MIN_GAMES = 3
TOP_RIVALRIES = 3
TOP_DUOS = 3
MAX_CHARS = 1900   # Discord allows 2000 per message


def esc(name):
    """Escape Discord markdown so names like *star* or __x__ show as typed."""
    return re.sub(r'([\\*_~`|>#\-\[\]()])', r'\\\1', name)


def is_warmup(game):
    return game.get('map', '').lower().startswith(WARMUP_PREFIXES)


def night_label(night):
    d = date.fromisoformat(night)
    return f'{d:%b} {d.day}'


def build_recap(games):
    """{'night', 'games', 'text'} for the latest night with real games, or None."""
    real = [g for g in games if g.get('night') and not is_warmup(g)]
    if not real:
        return None
    night = max(g['night'] for g in real)
    tonight = [g for g in real if g['night'] == night]

    names = {}
    kills = Counter()                       # (killer, victim) -> kills
    duo = defaultdict(lambda: [0, 0])       # (a, b) -> [wins, losses] on the same team
    for g in tonight:
        team = {p['id']: p.get('team') for p in g['p']}
        for p in g['p']:
            if (p.get('r') or 0) >= MIN_ROUNDS:
                names[p['id']] = p['n']
        for k in g.get('kp', []):
            killer, victim = k[2], k[3]
            if killer != victim and team.get(killer) != team.get(victim):
                kills[(killer, victim)] += 1
        if g.get('fin'):
            ps = [p for p in g['p'] if p.get('res') in ('W', 'L') and (p.get('r') or 0) >= MIN_ROUNDS]
            for a, b in itertools.combinations(ps, 2):
                if a.get('team') == b.get('team'):
                    duo[tuple(sorted((a['id'], b['id'])))][a['res'] == 'L'] += 1
    ids = sorted(names, key=lambda i: names[i].lower())

    # nemesis: most kills on you; ties broken by the more lopsided score, then name
    nemesis = {}
    for v in ids:
        best = max(
            (a for a in ids if a != v),
            key=lambda a: (kills[(a, v)], kills[(a, v)] - kills[(v, a)], names[a].lower()),
            default=None,
        )
        if best is not None and kills[(best, v)] >= NEMESIS_MIN_KILLS:
            nemesis[v] = best

    done, rows = set(), []
    for v, a in nemesis.items():
        if v in done:
            continue
        if nemesis.get(a) == v:
            done.update((v, a))
            x, y = kills[(v, a)], kills[(a, v)]
            first, second, x, y = (v, a, x, y) if x >= y else (a, v, y, x)
            note = 'dead even' if x == y else "each other's nemesis"
            rows.append((x - y, x + y, f'- {esc(names[first])} ⇄ {esc(names[second])}: **{x}-{y}**, {note}'))
        else:
            them, me = kills[(a, v)], kills[(v, a)]
            rows.append((them - me, them + me, f'- {esc(names[v])}: {esc(names[a])} got you **{them}-{me}**'))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    lines_nemesis = [r[2] for r in rows]

    rivalries = sorted(
        ((kills[(a, b)] + kills[(b, a)], a, b) for a, b in itertools.combinations(ids, 2)),
        key=lambda r: (-r[0], names[r[1]].lower(), names[r[2]].lower()),
    )[:TOP_RIVALRIES]
    lines_rivals = []
    for total, a, b in rivalries:
        if not total:
            continue
        x, y = kills[(a, b)], kills[(b, a)]
        if y > x:
            a, b, x, y = b, a, y, x
        lines_rivals.append(f'- {esc(names[a])} vs {esc(names[b])}: {x}-{y}')

    streaks = [(r, a, b) for (a, b), r in duo.items() if sum(r) >= DUO_MIN_GAMES and 0 in r]
    order = lambda s: (-sum(s[0]), names[s[1]].lower(), names[s[2]].lower())
    unbeaten = sorted((s for s in streaks if s[0][1] == 0), key=order)[:TOP_DUOS]
    winless = sorted((s for s in streaks if s[0][0] == 0), key=order)[:TOP_DUOS]
    fmt = lambda s: f'{esc(names[s[1]])} + {esc(names[s[2]])} {s[0][0]}-{s[0][1]}'

    head = f"**🔥 Last night's grudges** ({night_label(night)}, {len(tonight)} games)"
    sections = []
    if lines_nemesis:
        sections.append(['**Nemesis** (who killed you most)'] + lines_nemesis)
    if lines_rivals:
        sections.append(['**Biggest rivalries**'] + lines_rivals)
    duo_lines = []
    if unbeaten:
        duo_lines.append('- 🟢 Unbeaten together: ' + ', '.join(map(fmt, unbeaten)))
    if winless:
        duo_lines.append('- 🔴 Never won together: ' + ', '.join(map(fmt, winless)))
    if duo_lines:
        sections.append(['**Duos**'] + duo_lines)
    if not sections:
        return None

    text = head + '\n\n' + '\n\n'.join('\n'.join(s) for s in sections)
    # keep under Discord's limit by dropping the mildest nemesis lines
    while len(text) > MAX_CHARS and sections and len(sections[0]) > 2:
        sections[0].pop()
        text = head + '\n\n' + '\n\n'.join('\n'.join(s) for s in sections)
    return {'night': night, 'games': len(tonight), 'text': text}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', default=os.path.join(HERE, '..', 'data', 'games'))
    args = ap.parse_args()
    games = []
    for path in sorted(glob.glob(os.path.join(args.data, '*.json'))):
        with open(path, encoding='utf-8') as fh:
            games.append(json.load(fh))
    recap = build_recap(games)
    print(recap['text'] if recap else 'No games to recap.')


if __name__ == '__main__':
    main()
