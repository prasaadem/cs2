#!/usr/bin/env python3
"""Build a self-contained CS2 stats site from DatHost server logs.

Usage:
    python build_stats.py                      # reads ../logs, writes ../docs/index.html
    python build_stats.py --logs PATH --out FILE --utc-offset -7

Each night is the local date of the match start, minus 6 hours, so a session
that runs past midnight stays on one night.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

LINE = re.compile(r'^L (\d\d)/(\d\d)/(\d{4}) - (\d\d):(\d\d):(\d\d): (.*)$')
P = r'"(.+?)<\d+><\[U:1:(\d+)\]><(\w*)>"'
KILL = re.compile(P + r' \[[^\]]*\] killed ' + P + r' \[[^\]]*\] with "(\w+)"(.*)')
ASSIST = re.compile(P + r' assisted killing ' + P)
FLASH_ASSIST = re.compile(P + r' flash-assisted killing ' + P)
SUICIDE = re.compile(P + r' \[[^\]]*\] committed suicide with "(\w+)"')
BOMB = re.compile(P + r' triggered "(Planted_The_Bomb|Defused_The_Bomb)"')
NOTICE = re.compile(r'Team "(CT|TERRORIST)" triggered "SFUI_Notice_(\w+)" \(CT "(\d+)"\) \(T "(\d+)"\)')
DRAW = re.compile(r'World triggered "SFUI_Notice_Round_Draw"')
GAME_OVER = re.compile(r'Game Over: \w+\s+(\S+) score (\d+):(\d+) after (\d+) min')
MAP = re.compile(r'(?:Loading map|Match_Start" on) "(\w+)"')
ANY_PLAYER = re.compile(P)
SWITCH = re.compile(r'"(.+?)<\d+><\[U:1:(\d+)\]>" switched from team <\w+> to <(\w+)>')
DISCONNECT = re.compile(P + r' disconnected')
JSON_KV = re.compile(r'^"(round_number|score_t|score_ct)" : "(\d+)"')
JSON_PLAYER = re.compile(r'^"player_\d+" : "(.*)"')

KNIVES = ('knife', 'bayonet')


def is_knife(w):
    return w.startswith(KNIVES)


def read_groups(logdir):
    """Pair each header log with its _001 continuation file(s)."""
    groups = []
    for f in sorted(glob.glob(os.path.join(logdir, '*.log'))):
        if re.search(r'_\d{3}\.log$', f) and groups:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


class Match:
    def __init__(self, mp, start, roster):
        self.roster = roster        # players currently on CT/T (shared across the log)
        self.map = mp
        self.start = start
        self.end = start
        self.rounds = []            # winner per round: 'CT' / 'T' / None (draw)
        self.round_kills = [[]]     # kills per round: (attacker, victim)
        self.present = [set()]      # players seen per round
        self.stats = collections.defaultdict(collections.Counter)
        self.weapons = collections.defaultdict(collections.Counter)
        self.names = {}
        self.team = {}
        self.json = None            # last round_stats block: (rounds, {id: dmg})
        self.game_over = None

    def see(self, name, sid, team):
        self.names[sid] = name
        if team in ('CT', 'TERRORIST'):
            self.team[sid] = 'CT' if team == 'CT' else 'T'
            self.present[-1].add(sid)
            self.roster[sid] = name

    def end_round(self, winner):
        # everyone on a team at round end played it, even with no kill/death/buy
        for sid, name in self.roster.items():
            self.present[-1].add(sid)
            self.names.setdefault(sid, name)
        self.rounds.append(winner)
        self.round_kills.append([])
        self.present.append(set())


def parse_group(files, tz):
    matches = []
    cur = None
    mp = None
    json_buf = None
    roster = {}
    for f in files:
        with open(f, encoding='utf-8', errors='replace') as fh:
            for raw in fh:
                m = LINE.match(raw.rstrip('\n'))
                if not m:
                    continue
                mo, d, y, hh, mi, ss, msg = m.groups()
                t = dt.datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss),
                                tzinfo=dt.timezone.utc).astimezone(tz)

                # round_stats JSON blocks span several lines
                if 'JSON_BEGIN' in msg:
                    json_buf = {'players': {}}
                    continue
                if json_buf is not None:
                    kv = JSON_KV.match(msg)
                    if kv:
                        json_buf[kv.group(1)] = int(kv.group(2))
                    pm = JSON_PLAYER.match(msg)
                    if pm:
                        cols = [c.strip() for c in pm.group(1).split(',')]
                        json_buf['players'][cols[0]] = float(cols[6])
                    if 'JSON_END' in msg:
                        if cur is not None and cur.game_over is None:
                            r = json_buf.get('score_t', 0) + json_buf.get('score_ct', 0)
                            cur.json = (r, json_buf['players'])
                        json_buf = None
                    continue

                mm = MAP.search(msg)
                if mm:
                    mp = mm.group(1)
                if 'Match_Start' in msg:
                    # A new Match_Start means a restart: an unfinished match is
                    # discarded unless the log ends, so only real games survive.
                    if cur is not None and cur.game_over is not None:
                        matches.append(cur)
                    cur = Match(mp, t, roster)
                    continue
                sw = SWITCH.search(msg)
                if sw:
                    if sw.group(3) in ('CT', 'TERRORIST'):
                        roster[sw.group(2)] = sw.group(1)
                        if cur is not None and cur.game_over is None:
                            cur.see(*sw.groups())
                    else:
                        roster.pop(sw.group(2), None)
                    continue
                dc = DISCONNECT.search(msg)
                if dc:
                    roster.pop(dc.group(2), None)
                    continue
                if cur is None or cur.game_over is not None:
                    continue
                cur.end = t

                k = KILL.search(msg)
                if k:
                    an, aid, at, vn, vid, vt, w, rest = k.groups()
                    cur.see(an, aid, at)
                    cur.see(vn, vid, vt)
                    s, v = cur.stats[aid], cur.stats[vid]
                    v['d'] += 1
                    if at == vt:
                        s['tk'] += 1
                        continue
                    s['k'] += 1
                    cur.weapons[aid][w] += 1
                    if 'headshot' in rest:
                        s['hs'] += 1
                    if 'penetrated' in rest:
                        s['wb'] += 1
                    if 'noscope' in rest:
                        s['ns'] += 1
                    if 'throughsmoke' in rest:
                        s['smoke'] += 1
                    if 'attackerblind' in rest:
                        s['blindk'] += 1
                    if is_knife(w):
                        s['knife'] += 1
                    if w == 'awp':
                        s['awp'] += 1
                    if not cur.round_kills[-1]:
                        s['ek'] += 1
                        v['ed'] += 1
                    cur.round_kills[-1].append((aid, vid))
                    continue
                a = FLASH_ASSIST.search(msg)
                if a:
                    cur.see(*a.groups()[:3])
                    cur.stats[a.group(2)]['fa'] += 1
                    continue
                a = ASSIST.search(msg)
                if a:
                    cur.see(*a.groups()[:3])
                    cur.stats[a.group(2)]['a'] += 1
                    continue
                s = SUICIDE.search(msg)
                if s:
                    name, sid, team, w = s.groups()
                    if w != 'world':  # 'world' = team switch / join, not a real death
                        cur.see(name, sid, team)
                        cur.stats[sid]['d'] += 1
                        cur.stats[sid]['sui'] += 1
                    continue
                b = BOMB.search(msg)
                if b:
                    cur.see(*b.groups()[:3])
                    cur.stats[b.group(2)]['plant' if b.group(4).startswith('Planted') else 'defuse'] += 1
                    continue
                n = NOTICE.search(msg)
                if n:
                    cur.end_round('CT' if n.group(1) == 'CT' else 'T')
                    continue
                if DRAW.search(msg):
                    cur.end_round(None)
                    continue
                g = GAME_OVER.search(msg)
                if g:
                    cur.game_over = (int(g.group(2)), int(g.group(3)), int(g.group(4)))
                    continue
                for pm in ANY_PLAYER.finditer(msg):
                    cur.see(*pm.groups())
    if cur is not None and (cur.game_over is not None or cur.rounds):
        matches.append(cur)
    return matches


def rating(k, d, rounds, mk):
    """HLTV 1.0-style rating from kills, deaths, rounds and multi-kill rounds."""
    if rounds <= 0:
        return 0.0
    kpr = k / rounds
    spr = max(rounds - d, 0) / rounds
    rmk = (mk[1] + 4 * mk[2] + 9 * mk[3] + 16 * mk[4] + 25 * mk[5]) / rounds
    return (kpr / 0.679 + 0.7 * spr / 0.317 + rmk / 1.277) / 2.7


def build_game(m, gid):
    nrounds = len(m.rounds)
    finished = m.game_over is not None
    ct = sum(1 for r in m.rounds if r == 'CT')
    t = sum(1 for r in m.rounds if r == 'T')
    if finished:
        ct, t = m.game_over[0], m.game_over[1]
    winner = None
    if finished and ct != t:
        winner = 'CT' if ct > t else 'T'

    json_rounds, json_dmg = m.json if m.json else (0, {})
    players = []
    ids = set(m.stats) | {sid for r in m.present for sid in r}
    for sid in ids:
        if sid not in m.team:
            continue  # never on a side during this match
        s = m.stats[sid]
        played = sum(1 for i in range(nrounds) if sid in m.present[i])
        if played == 0 and not s['k'] and not s['d']:
            continue
        played = max(played, 1)
        mk = collections.Counter()
        for i in range(nrounds + 1):
            n = sum(1 for a, _ in m.round_kills[i] if a == sid)
            if n:
                mk[min(n, 5)] += 1
        dmg_rounds = sum(1 for i in range(min(json_rounds, nrounds)) if sid in m.present[i])
        dmg = json_dmg.get(sid)
        team = m.team[sid]
        players.append({
            'id': sid, 'n': m.names[sid], 'team': team,
            'res': ('W' if team == winner else 'L') if winner else None,
            'r': played, 'k': s['k'], 'd': s['d'], 'a': s['a'], 'fa': s['fa'],
            'hs': s['hs'], 'tk': s['tk'], 'sui': s['sui'],
            'ek': s['ek'], 'ed': s['ed'], 'k1': mk[1], 'k2': mk[2], 'k3': mk[3], 'k4': mk[4], 'k5': mk[5],
            'awp': s['awp'], 'knife': s['knife'], 'wb': s['wb'], 'ns': s['ns'],
            'smoke': s['smoke'], 'blindk': s['blindk'],
            'plant': s['plant'], 'defuse': s['defuse'],
            'dmg': dmg if dmg is not None and dmg_rounds else None,
            'dmgR': dmg_rounds if dmg is not None else 0,
            'rt': round(rating(s['k'], s['d'], played, mk), 3),
            'w': dict(m.weapons[sid].most_common()),
        })
    players.sort(key=lambda p: (-p['rt'], -p['k']))
    night = (m.start - dt.timedelta(hours=6)).date().isoformat()
    return {
        'id': gid, 'map': m.map, 'night': night,
        'start': m.start.strftime('%Y-%m-%dT%H:%M'),
        'min': m.game_over[2] if finished else max(1, round((m.end - m.start).total_seconds() / 60)),
        'fin': finished, 'ct': ct, 't': t, 'win': winner,
        'rounds': ''.join({'CT': 'C', 'T': 'T', None: '-'}[r] for r in m.rounds),
        'p': players,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--logs', default=os.path.join(HERE, '..', 'logs'))
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'docs', 'index.html'))
    ap.add_argument('--template', default=os.path.join(HERE, 'template.html'))
    ap.add_argument('--utc-offset', type=float, default=None,
                    help='hours from UTC for local times (default: this computer\'s timezone)')
    ap.add_argument('--min-rounds', type=int, default=3,
                    help='skip matches with fewer rounds than this (default 3)')
    ap.add_argument('--title', default='CS2 Nights')
    args = ap.parse_args()

    tz = (dt.timezone(dt.timedelta(hours=args.utc_offset)) if args.utc_offset is not None
          else dt.datetime.now().astimezone().tzinfo)

    matches = []
    for g in read_groups(args.logs):
        matches.extend(parse_group(g, tz))
    matches.sort(key=lambda m: m.start)

    games = []
    for m in matches:
        if len(m.rounds) < args.min_rounds:
            continue
        game = build_game(m, len(games) + 1)
        if len(game['p']) >= 2:
            games.append(game)

    data = {
        'title': args.title,
        'generated': dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M'),
        'games': games,
    }
    payload = json.dumps(data, separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/')
    with open(args.template, encoding='utf-8') as fh:
        html = fh.read()
    html = html.replace('/*__DATA__*/null', payload).replace('__TITLE__', args.title)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(html)

    nights = sorted({g['night'] for g in games})
    print(f'{len(games)} games ({sum(g["fin"] for g in games)} finished) over {len(nights)} nights '
          f'-> {os.path.abspath(args.out)}')


if __name__ == '__main__':
    main()
