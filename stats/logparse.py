"""Parse CS2 (DatHost) server logs into per-game stat dicts.

Times in the logs are UTC. Each game gets a stable id from its UTC start time
and map, so re-parsing the same log always yields the same id.
"""
import collections
import datetime as dt
import glob
import os
import re

PARSER_VERSION = 2  # 2: grenades, flashes, purchases, picked-up kills

# Local time for display / night grouping: US Pacific with US daylight-saving rules.
STD_OFFSET_HOURS = -8


def _nth_sunday(year, month, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def to_local(t_utc):
    """Convert an aware UTC datetime to US Pacific local time (handles PDT/PST)."""
    y = t_utc.year
    std = dt.timedelta(hours=STD_OFFSET_HOURS)
    # DST: 2nd Sunday of March 02:00 local standard -> 1st Sunday of November 02:00 local daylight
    dst_start = dt.datetime.combine(_nth_sunday(y, 3, 2), dt.time(2)) - std
    dst_end = dt.datetime.combine(_nth_sunday(y, 11, 1), dt.time(2)) - std - dt.timedelta(hours=1)
    naive = t_utc.replace(tzinfo=None)
    off = std + (dt.timedelta(hours=1) if dst_start <= naive < dst_end else dt.timedelta(0))
    return (naive + off).replace(tzinfo=dt.timezone(off))

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
THREW = re.compile(P + r' threw (hegrenade|flashbang|smokegrenade|molotov|decoy)\b')
PURCHASE = re.compile(P + r' purchased "(\w+)"')
BLIND = re.compile(P + r' blinded for ([\d.]+) by ' + P + r' from flashbang')

THROW_KEY = {'hegrenade': 'gh', 'flashbang': 'gf', 'smokegrenade': 'gs', 'molotov': 'gm', 'decoy': 'gd'}
# Weapons everyone spawns with, plus utility: a kill with these says nothing about picking up.
NOT_PICKUP = {'glock', 'hkp2000', 'usp_silencer', 'taser', 'hegrenade', 'inferno', 'molotov',
              'incgrenade', 'flashbang', 'smokegrenade', 'decoy', 'world'}
# CS2 list prices, used to estimate money spent (armor and kits are not logged).
PRICES = {
    'ak47': 2700, 'm4a1': 3100, 'm4a1_silencer': 2900, 'awp': 4750, 'aug': 3300, 'sg556': 3000,
    'famas': 2050, 'galilar': 1800, 'ssg08': 1700, 'g3sg1': 5000, 'scar20': 5000,
    'deagle': 700, 'tec9': 500, 'fiveseven': 500, 'cz75a': 500, 'p250': 300, 'elite': 300,
    'revolver': 600, 'glock': 200, 'hkp2000': 200, 'usp_silencer': 200,
    'p90': 2350, 'mp7': 1500, 'mp5sd': 1500, 'mac10': 1050, 'mp9': 1250, 'ump45': 1200, 'bizon': 1400,
    'nova': 1050, 'xm1014': 2000, 'mag7': 1300, 'sawedoff': 1100, 'negev': 1700, 'm249': 5200,
    'hegrenade': 300, 'flashbang': 200, 'smokegrenade': 300, 'molotov': 400, 'incgrenade': 500,
    'decoy': 50, 'taser': 200,
}
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
        self.weapon_hs = collections.defaultdict(collections.Counter)
        self.bought = collections.defaultdict(collections.Counter)    # purchases per player
        self.picked = collections.defaultdict(collections.Counter)    # kills with weapons not bought
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


def parse_group(files):
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
                                tzinfo=dt.timezone.utc)

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
                        cur.weapon_hs[aid][w] += 1
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
                    if w == 'taser':
                        s['zeus'] += 1
                    if w in ('hegrenade', 'inferno'):
                        s['nade'] += 1
                    if w not in NOT_PICKUP and not is_knife(w) and not cur.bought[aid][w]:
                        cur.picked[aid][w] += 1
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
                th = THREW.search(msg)
                if th:
                    cur.see(*th.groups()[:3])
                    cur.stats[th.group(2)][THROW_KEY[th.group(4)]] += 1
                    continue
                pu = PURCHASE.search(msg)
                if pu:
                    cur.see(*pu.groups()[:3])
                    cur.bought[pu.group(2)][pu.group(4)] += 1
                    continue
                bl = BLIND.search(msg)
                if bl:
                    vn, vid, vt, dur, an, aid, at = bl.groups()
                    cur.see(vn, vid, vt)
                    cur.see(an, aid, at)
                    dur = float(dur)
                    if vid == aid:
                        cur.stats[aid]['fself'] += 1
                    elif vt == at:
                        cur.stats[aid]['ft'] += 1
                    else:
                        cur.stats[aid]['fe'] += 1
                        cur.stats[aid]['fdur_ms'] += round(dur * 1000)
                        cur.stats[vid]['fbd'] += 1
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


def build_game(m):
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
    # Picked-up kills only make sense where people buy (aim/fy maps hand out weapons)
    economy = sum(sum(c.values()) for c in m.bought.values()) >= nrounds
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
            'zeus': s['zeus'], 'nade': s['nade'],
            'w': dict(m.weapons[sid].most_common()),
            'wh': dict(m.weapon_hs[sid]),
            'gh': s['gh'], 'gf': s['gf'], 'gs': s['gs'], 'gm': s['gm'], 'gd': s['gd'],
            'fe': s['fe'], 'ft': s['ft'], 'fself': s['fself'], 'fbd': s['fbd'],
            'fdur': round(s['fdur_ms'] / 1000, 1),
            'buy': sum(m.bought[sid].values()),
            'spent': sum(PRICES.get(i, 0) * c for i, c in m.bought[sid].items()),
            'bi': dict(m.bought[sid].most_common()),
            'pk': sum(m.picked[sid].values()) if economy else None,
            'pkw': dict(m.picked[sid].most_common()) if economy else {},
        })
    players.sort(key=lambda p: (-p['rt'], -p['k']))
    local = to_local(m.start)
    # a session that runs past midnight stays on one night
    night = (local - dt.timedelta(hours=6)).date().isoformat()
    return {
        'id': m.start.strftime('%Y%m%d-%H%M') + '-' + m.map,
        'v': PARSER_VERSION,
        'map': m.map, 'night': night,
        'start_utc': m.start.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'start': local.strftime('%Y-%m-%dT%H:%M'),
        'min': m.game_over[2] if finished else max(1, round((m.end - m.start).total_seconds() / 60)),
        'economy': economy,
        'fin': finished, 'ct': ct, 't': t, 'win': winner,
        'rounds': ''.join({'CT': 'C', 'T': 'T', None: '-'}[r] for r in m.rounds),
        'p': players,
    }


def parse_logs(logdir, min_rounds=3):
    """Parse every log in logdir and return the list of game dicts, oldest first."""
    matches = []
    for g in read_groups(logdir):
        matches.extend(parse_group(g))
    matches.sort(key=lambda m: m.start)
    games = []
    for m in matches:
        if len(m.rounds) < min_rounds:
            continue
        game = build_game(m)
        if len(game['p']) >= 2:
            games.append(game)
    return games
