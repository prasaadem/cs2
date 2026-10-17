"""Parse CS2 (DatHost) server logs into per-game stat dicts.

Times in the logs are UTC. Each game gets a stable id from its UTC start time
and map, so re-parsing the same log always yields the same id.
"""
import collections
import datetime as dt
import glob
import os
import re

PARSER_VERSION = 4  # 2: grenades/flashes/purchases; 3: clutches/trades/bomb/round ends; 4: economy, round-stat extras

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
BOMB = re.compile(P + r' triggered "(Planted_The_Bomb|Defused_The_Bomb)"(?: at bombsite (\w))?')
BOMB_CARRY = re.compile(P + r' triggered "(Got_The_Bomb|Dropped_The_Bomb)"')
ROUND_START = 'World triggered "Round_Start"'
# how a round ended, from the SFUI notice: e=elimination, b=bomb exploded, d=defused, t=time ran out
END_REASON = {'CTs_Win': 'e', 'Terrorists_Win': 'e', 'Target_Bombed': 'b', 'Bomb_Defused': 'd', 'Target_Saved': 't'}
TRADE_SECONDS = 5
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
JSON_FIELDS = re.compile(r'^"fields" : "(.*)"')
DEFAULT_FIELDS = ('accountid,team,money,kills,deaths,assists,dmg,hsp,kdr,adr,mvp,ef,ud,3k,4k,5k,clutchk,'
                  'firstk,pistolk,sniperk,blindk,bombk,firedmg,uniquek,dinks,chickenk').split(',')
OTHER_KILL = re.compile(P + r' \[[^\]]*\] killed other "(\w+)<')

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
        self.reasons = []           # per round: END_REASON code
        self.plants = []            # per round: bombsite planted ('A'/'B') or '-'
        self.sides = []             # per round: {player: 'C'/'T'}
        self.clutches = collections.defaultdict(list)   # player -> [[vs, won], ...]
        self.alive = {}             # player -> 'CT'/'T' while the round is live
        self.clutch = {}            # side -> (player, enemies alive when the clutch began)
        self.recent = []            # this round's kills: [time, killer, killer side, victim]
        self.bomb_dropped = False
        self.plant = '-'
        self.money = {}             # round index -> {player: money at round start}
        self.spend = collections.defaultdict(collections.Counter)  # round index -> {player: $ spent}

    def start_round(self):
        self.alive = {sid: self.team[sid] for sid in self.roster if sid in self.team}
        self.clutch, self.recent, self.bomb_dropped, self.plant = {}, [], False, '-'

    def died(self, sid):
        """Remove a player from the living; start a clutch when one player is left on a side."""
        if self.alive.pop(sid, None) is None:
            return
        for side in ('CT', 'T'):
            left = [p for p, s in self.alive.items() if s == side]
            enemies = sum(1 for s in self.alive.values() if s != side)
            if len(left) == 1 and enemies and side not in self.clutch:
                self.clutch[side] = (left[0], enemies)

    def see(self, name, sid, team):
        self.names[sid] = name
        if team in ('CT', 'TERRORIST'):
            self.team[sid] = 'CT' if team == 'CT' else 'T'
            self.present[-1].add(sid)
            self.roster[sid] = name

    def end_round(self, winner, reason='e'):
        # everyone on a team at round end played it, even with no kill/death/buy
        for sid, name in self.roster.items():
            self.present[-1].add(sid)
            self.names.setdefault(sid, name)
        for side, (sid, vs) in self.clutch.items():
            self.clutches[sid].append([vs, 1 if side == winner else 0])
        self.sides.append({sid: self.team[sid][0] for sid in self.present[-1] if sid in self.team})
        self.reasons.append(reason)
        self.plants.append(self.plant)
        self.alive, self.clutch, self.bomb_dropped = {}, {}, False
        self.rounds.append(winner)
        self.round_kills.append([])
        self.present.append(set())


def parse_group(files):
    matches = []
    cur = None
    mp = None
    json_buf = None
    last_json = None
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
                    json_buf = {'players': {}, 'fields': DEFAULT_FIELDS}
                    continue
                if json_buf is not None:
                    kv = JSON_KV.match(msg)
                    if kv:
                        json_buf[kv.group(1)] = int(kv.group(2))
                    fm = JSON_FIELDS.match(msg)
                    if fm:
                        json_buf['fields'] = [c.strip() for c in fm.group(1).split(',')]
                    pm = JSON_PLAYER.match(msg)
                    if pm:
                        cols = [c.strip() for c in pm.group(1).split(',')]
                        json_buf['players'][cols[0]] = dict(zip(json_buf['fields'], cols))
                    if 'JSON_END' in msg:
                        last_json = json_buf
                        if cur is not None and cur.game_over is None:
                            r = json_buf.get('score_t', 0) + json_buf.get('score_ct', 0)
                            cur.json = (r, json_buf['players'])
                            # the block is printed as a round begins: money is what each player starts it with
                            idx = json_buf.get('round_number', 0) - 1
                            if idx == len(cur.rounds):
                                cur.money[idx] = {sid: int(float(row.get('money', 0)))
                                                  for sid, row in json_buf['players'].items()}
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
                    # round 1's block is printed just before Match_Start
                    if last_json and last_json.get('round_number') == 1:
                        cur.money[0] = {sid: int(float(row.get('money', 0))) for sid, row in last_json['players'].items()}
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
                    if cur is not None and cur.game_over is None:
                        cur.died(dc.group(2))
                    continue
                if cur is None or cur.game_over is not None:
                    continue
                cur.end = t
                if ROUND_START in msg:
                    cur.start_round()
                    continue

                ok = OTHER_KILL.search(msg)
                if ok:
                    cur.see(*ok.groups()[:3])
                    if ok.group(4) == 'chicken':
                        cur.stats[ok.group(2)]['chick'] += 1
                    elif ok.group(4).startswith('func_breakable'):
                        cur.stats[ok.group(2)]['brk'] += 1
                    continue
                k = KILL.search(msg)
                if k:
                    an, aid, at, vn, vid, vt, w, rest = k.groups()
                    cur.see(an, aid, at)
                    cur.see(vn, vid, vt)
                    s, v = cur.stats[aid], cur.stats[vid]
                    v['d'] += 1
                    cur.died(vid)
                    if at == vt:
                        s['tk'] += 1
                        continue
                    side = 'CT' if at == 'CT' else 'T'
                    clutcher = cur.clutch.get(side)
                    if clutcher and clutcher[0] == aid:
                        s['ck'] += 1
                    # trade: killing the enemy who just killed a teammate
                    for ev in cur.recent:
                        if ev[1] == vid and ev[2] != side and (t - ev[0]).total_seconds() <= TRADE_SECONDS \
                                and cur.team.get(ev[3]) == side:
                            s['trade'] += 1
                            cur.stats[ev[3]]['traded'] += 1
                            ev[1] = None  # each death is traded once
                            break
                    cur.recent.append([t, aid, side, vid])
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
                        cur.died(sid)
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
                    cur.spend[len(cur.rounds)][pu.group(2)] += PRICES.get(pu.group(4), 0)
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
                    if b.group(4).startswith('Planted'):
                        cur.stats[b.group(2)]['plant'] += 1
                        cur.plant = b.group(5) or '?'
                        if b.group(5) in ('A', 'B'):
                            cur.stats[b.group(2)]['p' + b.group(5)] += 1
                    else:
                        cur.stats[b.group(2)]['defuse'] += 1
                    continue
                bc = BOMB_CARRY.search(msg)
                if bc:
                    cur.see(*bc.groups()[:3])
                    if bc.group(4) == 'Dropped_The_Bomb':
                        cur.stats[bc.group(2)]['bdrop'] += 1
                        cur.bomb_dropped = True
                    else:
                        cur.stats[bc.group(2)]['bpick' if cur.bomb_dropped else 'bspawn'] += 1
                    continue
                n = NOTICE.search(msg)
                if n:
                    cur.end_round('CT' if n.group(1) == 'CT' else 'T', END_REASON.get(n.group(2), 'e'))
                    continue
                if DRAW.search(msg):
                    cur.end_round(None, '-')
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


def pistol_rounds(m):
    """Round 1, plus each round where most players switched sides (half time)."""
    out = [0] if m.rounds else []
    for i in range(1, len(m.sides)):
        both = [p for p in m.sides[i] if p in m.sides[i - 1]]
        if both and sum(m.sides[i][p] != m.sides[i - 1][p] for p in both) * 2 > len(both):
            out.append(i)
    return out


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
        row = json_dmg.get(sid)
        dmg = float(row['dmg']) if row and row.get('dmg') else None
        extra = {}
        if row:
            for key, field in (('ud', 'ud'), ('fdmg', 'firedmg'), ('dinks', 'dinks'), ('uniq', 'uniquek')):
                try:
                    extra[key] = int(float(row[field]))
                except (KeyError, ValueError):
                    pass
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
            'cl': m.clutches.get(sid, []), 'ck': s['ck'],
            'trade': s['trade'], 'traded': s['traded'],
            'bspawn': s['bspawn'], 'bpick': s['bpick'], 'bdrop': s['bdrop'], 'pA': s['pA'], 'pB': s['pB'],
            'sd': ''.join(m.sides[i].get(sid, '.') for i in range(nrounds)),
            'chick': s['chick'], 'brk': s['brk'],
            'mo': [m.money.get(i, {}).get(sid) for i in range(nrounds)],
            'spr': [m.spend[i][sid] for i in range(nrounds)],
            **extra,
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
        'rr': ''.join(m.reasons),
        'rp': ''.join(m.plants),
        'pistol': pistol_rounds(m),
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
