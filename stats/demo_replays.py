#!/usr/bin/env python3
"""Turn GOTV demos into compact replay files for the site's replay viewer.

Usage:
    python stats/demo_replays.py --demos DIR [--out docs/data/replays] [--force]

Needs the demoparser2 package (pip install demoparser2). For each match in each
demo it writes docs/data/replays/<id>.json and updates index.json. The id is the
matching game's id from data/games when the stats have that game, so the game
page can link to its replay. Replays are kept forever; a demo is re-read only
when it has grown since last time (the server was still recording).

Replay format (positions are Hammer units, times are seconds from match start):
  players[i].x / .y   positions, delta-encoded (first value absolute, then differences)
  players[i].a        facing / 4 (0..89, degrees = value * 4)
  players[i].s        one char per sample: C/T alive, c/t dead, . not on the server
  rounds              [start, freeze end, end, winner C/T/-, reason]
  kills               [time, killer id, victim id, weapon, headshot, kx, ky, vx, vy]
  grenades            [type s/m/h/f/d, thrower id, thrown, landed, effect ends, path] where path is
                      x,y pairs every 1/16 s from the throw to the landing (delta-encoded)
  shots               [time, player index] for every bullet fired
  hits                [time, attacker index, victim index, damage, hit group, weapon] (player_hurt)
  bomb                [time, event, player index, x, y, has kit] events: pick drop bp (begin plant)
                      ap (abort plant) plant bd (begin defuse) ad (abort defuse) defuse boom
  blind               [time, victim index, attacker index, seconds] (flashed players)
  players[i].w / .h   weapon held / health, run-length: [[sample, value], ...] (weapon = index into wn)
"""
import argparse
import datetime as dt
import glob
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TICKRATE = 64
SAMPLE_TICKS = 32          # two samples a second; the viewer interpolates between them
MATCH_WINDOW = 6 * 60      # a demo match and a logged game start within 6 minutes = same game
MIN_SECONDS = 30           # shorter fragments (restarts, map changes) aren't worth a replay
SIDE = {2: 'T', 3: 'C'}


def demo_start(path):
    """Recording start from DatHost's auto-record name, e.g. auto-20261017-0345-de_dust2-cupcake.dem."""
    m = re.search(r'(\d{8})-(\d{4,6})', os.path.basename(path))
    if m:
        d, t = m.group(1), m.group(2).ljust(6, '0')
        return dt.datetime.strptime(d + t, '%Y%m%d%H%M%S').replace(tzinfo=dt.timezone.utc)
    return dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)


def events(parser, name, **kw):
    try:
        df = parser.parse_event(name, **kw)
    except Exception:  # noqa: BLE001 - event absent from this demo
        return []
    if not hasattr(df, 'to_dict'):
        return []
    return df.to_dict('records')


def num(v, default=None):
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def delta(vals):
    out, prev = [], 0
    for v in vals:
        out.append(v - prev)
        prev = v
    return out


NOT_GUNS = ('knife', 'grenade', 'flashbang', 'molotov', 'decoy', 'incgrenade', 'c4', 'taser', 'bayonet')
PROJECTILE = {'CSmokeGrenadeProjectile': 's', 'CMolotovProjectile': 'm', 'CHEGrenadeProjectile': 'h',
              'CFlashbangProjectile': 'f', 'CDecoyProjectile': 'd'}
FLIGHT_TICKS = 4           # grenade paths are sampled 16 times a second
EFFECT_SECONDS = {'s': 20, 'm': 7, 'h': 0.5, 'f': 0.4, 'd': 15}  # fallback when the demo has no end event


def grenade_flights(p):
    """Each thrown grenade: (type, thrower steamid64, thrown tick, landed tick, effect-end tick, [(x, y), ...])."""
    try:
        g = p.parse_grenades()
    except Exception:  # noqa: BLE001
        return []
    if not len(g):
        return []
    g = g[g['grenade_type'].isin(PROJECTILE)].dropna(subset=['x', 'y'])
    smoke_pop = {int(e['entityid']): int(e['tick']) for e in events(p, 'smokegrenade_detonate')}
    # HE / flash / decoy projectiles linger in the demo after going off, so use their own detonation event
    detonate = {int(e['entityid']): int(e['tick'])
                for name in ('hegrenade_detonate', 'flashbang_detonate', 'decoy_started') for e in events(p, name)}
    smoke_end = {int(e['entityid']): int(e['tick']) for e in events(p, 'smokegrenade_expired')}
    fire_start = [(int(e['tick']), int(e['entityid'])) for e in events(p, 'inferno_startburn')]
    fire_end = {int(e['entityid']): int(e['tick']) for e in events(p, 'inferno_expire')}
    out = []
    for (gtype, eid), rows in g.groupby(['grenade_type', 'grenade_entity_id']):
        kind, eid = PROJECTILE[gtype], int(eid)
        rows = rows.sort_values('tick')
        t_throw = int(rows['tick'].iloc[0])
        if kind == 's' and eid in smoke_pop:
            t_land = smoke_pop[eid]                     # the projectile lingers in the smoke afterwards
        elif eid in detonate:
            t_land = detonate[eid]
        else:
            t_land = int(rows['tick'].iloc[-1])         # molotovs end where they burst
        fl = rows[rows['tick'] <= t_land]
        fl = fl[((fl['tick'] - t_throw) % FLIGHT_TICKS == 0) | (fl['tick'] == fl['tick'].max())]
        path = [(int(round(x)), int(round(y))) for x, y in zip(fl['x'], fl['y'])]
        if not path:
            continue
        if kind == 's':
            t_end = smoke_end.get(eid)
        elif kind == 'm':
            fire = next((fe for ft, fe in fire_start if 0 <= ft - t_land <= 8), None)
            t_end = fire_end.get(fire) if fire is not None else None
            if fire is None:
                kind = 'mx'  # landed somewhere it couldn't burn (e.g. extinguished in smoke)
        else:
            t_end = None
        if t_end is None:
            t_end = t_land + int(EFFECT_SECONDS.get(kind, 0.3) * TICKRATE)
        out.append((kind, str(rows['steamid'].iloc[0]), t_throw, t_land, t_end, path))
    return out


CELL = 'CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_cell'
VEC = 'CCSPlayerPawn.CBodyComponentBaseAnimGraph.m_vec'


def fill_positions(ticks):
    """Rebuild X/Y where the parser left them out. A position is a 512-unit cell plus an
    offset inside it; a cell that never changes is never sent, and its default (32) is
    the map origin, so then the coordinate is just the offset."""
    for axis in ('X', 'Y'):
        cell, vec = CELL + axis, VEC + axis
        if vec not in ticks.columns:
            continue
        if axis not in ticks.columns:
            ticks[axis] = float('nan')
        c = ticks[cell] if cell in ticks.columns else None
        if c is not None:
            c = c.groupby(ticks['steamid']).transform(lambda v: v.ffill().bfill())
            c = c.fillna(32)
        else:
            c = 32
        rebuilt = c * 512 - 16384 + ticks[vec]
        ticks[axis] = ticks[axis].fillna(rebuilt)
    return ticks


BOMB_EVENTS = {'bomb_pickup': 'pick', 'bomb_dropped': 'drop', 'bomb_beginplant': 'bp', 'bomb_abortplant': 'ap',
               'bomb_planted': 'plant', 'bomb_begindefuse': 'bd', 'bomb_abortdefuse': 'ad',
               'bomb_defused': 'defuse', 'bomb_exploded': 'boom'}


def _missing(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or str(v) in ('', 'nan', 'None')


def resolve_players(p, shots, hurts, deaths, grenades):
    """Fill in who fired / got hurt / died when the demo couldn't name the player.

    That happens for anyone already connected when the recording started (auto-record
    begins at a map change and misses their join). Their own state is still recorded,
    so: the shooter is whoever's ammo dropped on that tick, a hurt player is whoever's
    health dropped, a dead player is whoever stopped being alive; the attacker is whoever
    fired just before (or threw the grenade), the killer is whoever hurt them last.
    """
    need = [t for t, sid, name in shots if _missing(sid) and _missing(name)]
    need += [int(e['tick']) for e in hurts + deaths if _missing(e.get('user_steamid')) and _missing(e.get('user_name'))]
    if not need:
        return shots, hurts, deaths
    ticks = sorted({x for t in need for x in (t - 2, t + 1)})
    st = p.parse_ticks(['active_weapon_ammo', 'health', 'is_alive'], ticks=ticks)
    snap = {}
    for row in st.to_dict('records'):
        snap.setdefault(int(row['tick']), {})[str(int(row['steamid']))] = row

    def changed(t, field, test):
        before, after = snap.get(t - 2, {}), snap.get(t + 1, {})
        out = []
        for sid, r0 in before.items():
            r1 = after.get(sid)
            if r1 is not None and not _missing(r0.get(field)) and not _missing(r1.get(field)) and test(r0[field], r1[field]):
                out.append((sid, r0.get('name')))
        return out

    fixed_shots = []
    for t, sid, name in shots:
        if _missing(sid) and _missing(name):
            c = changed(t, 'active_weapon_ammo', lambda a, b: b < a)
            if c:
                sid, name = c[0]
        fixed_shots.append((t, sid, name))
    known = sorted((t, sid, name) for t, sid, name in fixed_shots if not _missing(sid))
    throws = {k: (sid, t_land) for k, sid, _, t_land, _, _ in [(g[0], g[1], g[2], g[3], g[4], g[5]) for g in grenades]}

    for e in hurts:
        t = int(e['tick'])
        if _missing(e.get('user_steamid')) and _missing(e.get('user_name')):
            c = changed(t, 'health', lambda a, b: b < a)
            if c:
                e['user_steamid'], e['user_name'] = c[0]
        if _missing(e.get('attacker_steamid')) and _missing(e.get('attacker_name')):
            w = str(e.get('weapon') or '')
            if w in ('inferno', 'molotov', 'incgrenade', 'hegrenade'):
                kind = 'h' if w == 'hegrenade' else 'm'
                cands = [g for g in grenades if g[0] == kind and g[3] <= t]
                if cands:
                    e['attacker_steamid'] = max(cands, key=lambda g: g[3])[1]
            elif w and w != 'world':
                prev = [k for k in known if t - 20 <= k[0] <= t and k[1] != e.get('user_steamid')]
                if prev:
                    e['attacker_steamid'], e['attacker_name'] = prev[-1][1], prev[-1][2]
    for e in deaths:
        t = int(e['tick'])
        if _missing(e.get('user_steamid')) and _missing(e.get('user_name')):
            c = changed(t, 'is_alive', lambda a, b: bool(a) and not bool(b))
            if c:
                e['user_steamid'], e['user_name'] = c[0]
        if _missing(e.get('attacker_steamid')) and _missing(e.get('attacker_name')):
            last = [h for h in hurts if int(h['tick']) <= t and h.get('user_steamid') == e.get('user_steamid')
                    and not _missing(h.get('attacker_steamid'))]
            if last:
                e['attacker_steamid'] = last[-1]['attacker_steamid']
    return fixed_shots, hurts, deaths


def load_games(data_dir):
    games = []
    for f in glob.glob(os.path.join(data_dir, '*.json')):
        with open(f, encoding='utf-8') as fh:
            g = json.load(fh)
        games.append((g['id'], g['map'], dt.datetime.strptime(g['start_utc'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)))
    return games


def convert(path, games):
    from demoparser2 import DemoParser  # imported here so --help works without it

    p = DemoParser(path)
    mp = p.parse_header().get('map_name', '?')
    t0 = demo_start(path)
    rstart = sorted(int(e['tick']) for e in events(p, 'round_start'))
    freeze = sorted(int(e['tick']) for e in events(p, 'round_freeze_end'))
    rends = sorted(events(p, 'round_end'), key=lambda e: e['tick'])
    deaths = events(p, 'player_death', player=['X', 'Y'])
    grenades = grenade_flights(p)
    # some demos leave the shooter's steamid empty; the name is still there
    shots_all = [(int(e['tick']), e.get('user_steamid'), e.get('user_name'))
                 for e in events(p, 'weapon_fire') if not str(e.get('weapon', '')).endswith(NOT_GUNS)]
    # a match begins at the server's restart/new-match events; otherwise the whole demo is one match
    starts = sorted({int(e['tick']) for n in ('begin_new_match', 'round_announce_match_start') for e in events(p, n)})
    ticks = p.parse_ticks(['X', 'Y', 'yaw', 'is_alive', 'team_num', 'active_weapon_name', 'health',
                           CELL + 'X', CELL + 'Y', VEC + 'X', VEC + 'Y'])
    if len(ticks):
        ticks = fill_positions(ticks)
        for col in ('yaw', 'is_alive', 'team_num', 'active_weapon_name', 'health'):
            if col not in ticks.columns:  # a field that never changed in this demo comes back missing
                ticks[col] = None
        if 'X' not in ticks.columns or 'Y' not in ticks.columns:
            return []
    hurts = events(p, 'player_hurt')
    bomb_ev = sorted(((code, e) for name, code in BOMB_EVENTS.items() for e in events(p, name)), key=lambda x: int(x[1]['tick']))
    blinds = events(p, 'player_blind')
    shots_all, hurts, deaths = resolve_players(p, shots_all, hurts, deaths, grenades)
    if not len(ticks):
        return []
    first, last = int(ticks['tick'].min()), int(ticks['tick'].max())
    bounds = (starts or [first]) + [last + 1]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        seg = ticks[(ticks['tick'] >= a) & (ticks['tick'] < b)]
        seg = seg[(seg['tick'] - a) % SAMPLE_TICKS == 0]
        if seg.empty:
            continue
        n = int((seg['tick'].max() - a) // SAMPLE_TICKS) + 1
        if n / (TICKRATE / SAMPLE_TICKS) < MIN_SECONDS:
            continue
        sec = lambda tk: round((tk - a) / TICKRATE, 1)  # noqa: E731
        players = []
        wnames = []
        track = {}  # player id -> (xs, ys) absolute positions, for kills without coordinates

        def rle(values):
            out, prev = [], object()
            for i, v in enumerate(values):
                if v != prev:
                    out.append([i, v])
                    prev = v
            return out
        for sid, rows in seg.groupby('steamid'):
            if not sid or str(sid) == '0':
                continue  # GOTV itself
            idx = ((rows['tick'] - a) // SAMPLE_TICKS).astype(int).tolist()
            xs, ys, as_, ss = [0] * n, [0] * n, [0] * n, ['.'] * n
            ws, hs = [None] * n, [None] * n
            lx = ly = 0
            for i, x, y, yaw, alive, team, wpn, hp in zip(idx, rows['X'], rows['Y'], rows['yaw'], rows['is_alive'],
                                                          rows['team_num'], rows['active_weapon_name'], rows['health']):
                side = SIDE.get(int(num(team, 0)))
                if not side:
                    continue  # spectator / unassigned
                if isinstance(wpn, str) and wpn:
                    if wpn not in wnames:
                        wnames.append(wpn)
                    ws[i] = wnames.index(wpn)
                h = num(hp)
                hs[i] = (int(h) if h is not None else None) if bool(alive) else 0  # unknown health stays None
                lx, ly = int(round(num(x, lx))), int(round(num(y, ly)))
                xs[i], ys[i] = lx, ly
                as_[i] = int(round((num(yaw, 0) % 360) / 4)) % 90
                ss[i] = side if bool(alive) else side.lower()
            # carry the last known position through gaps so deltas stay small
            for i in range(1, n):
                if ss[i] == '.':
                    xs[i], ys[i] = xs[i - 1], ys[i - 1]
            if all(c == '.' for c in ss):
                continue
            # steamid64 -> account id, the id the stats use
            sid64 = int(sid)
            pid = str(sid64 - 76561197960265728) if sid64 > 76561197960265728 else str(sid64)
            track[pid] = (xs, ys)
            for i in range(1, n):  # hold the last weapon / health through short gaps
                if ws[i] is None:
                    ws[i] = ws[i - 1]
                if hs[i] is None:
                    hs[i] = hs[i - 1]
            players.append({'id': pid, 'n': str(rows['name'].iloc[-1]), 'x': delta(xs), 'y': delta(ys), 'a': as_,
                            's': ''.join(ss), 'w': rle(ws), 'h': rle(hs)})
        if not players:
            continue
        rounds = []
        for e in rends:
            tk = int(e['tick'])
            if not a <= tk < b:
                continue
            st = max([s for s in rstart if s <= tk] or [a])
            fz = min([f for f in freeze if st <= f <= tk] or [st])
            w = num(e.get('winner'))
            rounds.append([sec(st), sec(fz), sec(tk), {2: 'T', 3: 'C'}.get(int(w), '-') if w is not None else '-',
                           str(e.get('reason') or '')])
        by_name = {pl['n']: pl['id'] for pl in players}

        def who(sid, name=None):
            """Account id for an event's player: by name (unique within a match), else by steamid64.
            The id is parsed from text, since 17-digit ids don't survive a trip through floats."""
            if isinstance(name, str) and name in by_name:
                return by_name[name]
            txt = str(sid).split('.')[0] if sid is not None else ''
            if txt.isdigit() and int(txt) > 76561197960265728:
                return str(int(txt) - 76561197960265728)
            return None

        def where(pid, tk, ex, ey):
            if num(ex) is not None and num(ey) is not None:
                return int(num(ex)), int(num(ey))
            if pid in track:
                k = max(0, min(n - 1, (tk - a) // SAMPLE_TICKS))
                return track[pid][0][k], track[pid][1][k]
            return None
        acct = who

        kills = []
        for e in deaths:
            tk = int(e['tick'])
            if not a <= tk < b:
                continue
            killer, victim = who(e.get('attacker_steamid'), e.get('attacker_name')), who(e.get('user_steamid'), e.get('user_name'))
            vpos = where(victim, tk, e.get('user_X'), e.get('user_Y'))
            if victim is None or vpos is None:
                continue
            kpos = where(killer, tk, e.get('attacker_X'), e.get('attacker_Y')) or vpos
            kills.append([sec(tk), killer, victim, str(e.get('weapon') or ''), 1 if e.get('headshot') else 0, *kpos, *vpos])
        nades = []
        for kind, sid, t_throw, t_land, t_end, path in grenades:
            if not a <= t_throw < b:
                continue
            flat = [c for xy in path for c in xy]
            nades.append([kind, acct(sid), sec(t_throw), sec(t_land), sec(t_end),
                          [v for pair in zip(delta(flat[0::2]), delta(flat[1::2])) for v in pair]])
        pidx = {pl['id']: i for i, pl in enumerate(players)}
        shots = [[sec(tk), pidx[who(sid, name)]] for tk, sid, name in shots_all if a <= tk < b and who(sid, name) in pidx]
        hits = []
        for e in hurts:
            tk = int(e['tick'])
            att, vic = who(e.get('attacker_steamid'), e.get('attacker_name')), who(e.get('user_steamid'), e.get('user_name'))
            if not a <= tk < b or vic not in pidx:
                continue
            hits.append([sec(tk), pidx.get(att), pidx[vic], int(num(e.get('dmg_health'), 0)),
                         str(e.get('hitgroup') or ''), str(e.get('weapon') or '')])
        bomb = []
        last_plant = None
        for code, e in bomb_ev:
            tk = int(e['tick'])
            if not a <= tk < b:
                continue
            pid = who(e.get('user_steamid'), e.get('user_name'))
            pos = where(pid, tk, None, None) if pid else None
            if code == 'plant':
                last_plant = pos
            if code == 'boom' and pos is None:
                pos = last_plant  # the explosion has no player; it happens where the bomb was planted
            bomb.append([sec(tk), code, pidx.get(pid), *(pos or (None, None)), 1 if e.get('haskit') else 0])
        blind = []
        for e in blinds:
            tk = int(e['tick'])
            vic = who(e.get('user_steamid'), e.get('user_name'))
            if not a <= tk < b or vic not in pidx:
                continue
            blind.append([sec(tk), pidx[vic], pidx.get(who(e.get('attacker_steamid'), e.get('attacker_name'))),
                          round(num(e.get('blind_duration'), 0), 1)])
        start = t0 + dt.timedelta(seconds=a / TICKRATE)
        game = min((g for g in games if g[1] == mp and abs((g[2] - start).total_seconds()) <= MATCH_WINDOW),
                   key=lambda g: abs((g[2] - start).total_seconds()), default=None)
        rid = game[0] if game else start.strftime('%Y%m%d-%H%M') + '-' + mp
        out.append({'id': rid, 'game': game[0] if game else None, 'map': mp,
                    'start_utc': start.strftime('%Y-%m-%dT%H:%M:%SZ'), 'hz': TICKRATE / SAMPLE_TICKS, 'n': n,
                    'players': players, 'rounds': rounds, 'kills': kills, 'grenades': nades, 'shots': shots,
                    'hits': hits, 'wn': wnames, 'bomb': bomb, 'blind': blind})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--demos', required=True, help='folder with .dem files')
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'docs', 'data', 'replays'))
    ap.add_argument('--data', default=os.path.join(HERE, '..', 'data', 'games'))
    ap.add_argument('--force', action='store_true', help='re-read every demo')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    idx_path = os.path.join(args.out, 'index.json')
    index = {'replays': [], 'demos': {}}
    if os.path.exists(idx_path):
        with open(idx_path, encoding='utf-8') as fh:
            index = json.load(fh)
    games = load_games(args.data)
    done = index.setdefault('demos', {})
    by_id = {r['id']: r for r in index.get('replays', [])}
    changed = 0
    for path in sorted(glob.glob(os.path.join(args.demos, '*.dem'))):
        name, size = os.path.basename(path), os.path.getsize(path)
        prev = done.get(name) or {}
        if not args.force and prev.get('size') == size:
            continue
        try:
            reps = convert(path, games)
        except Exception as e:  # noqa: BLE001 - one broken demo must not stop the rest
            print(f'  ! {name}: {e}')
            continue
        # a demo read again (it grew while recording) replaces what it produced last time
        for old in set(prev.get('ids', [])) - {r['id'] for r in reps}:
            by_id.pop(old, None)
            try:
                os.remove(os.path.join(args.out, old + '.json'))
            except OSError:
                pass
        for r in reps:
            with open(os.path.join(args.out, r['id'] + '.json'), 'w', encoding='utf-8') as fh:
                json.dump(r, fh, ensure_ascii=False, separators=(',', ':'))
            by_id[r['id']] = {'id': r['id'], 'game': r['game'], 'map': r['map'], 'start_utc': r['start_utc'],
                              'dur': round(r['n'] / r['hz']), 'rounds': len(r['rounds']),
                              'players': [pl['n'] for pl in r['players']]}
            print(f'  + {r["id"]}: {len(r["players"])} players, {len(r["rounds"])} rounds, {r["n"] / r["hz"] / 60:.1f} min'
                  + (' (matched to stats)' if r['game'] else ''))
            changed += 1
        done[name] = {'size': size, 'ids': [r['id'] for r in reps]}
    # replays recorded before their game reached the stats get linked once it does
    for rid, r in list(by_id.items()):
        if r.get('game'):
            continue
        start = dt.datetime.strptime(r['start_utc'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
        game = min((g for g in games if g[1] == r['map'] and abs((g[2] - start).total_seconds()) <= MATCH_WINDOW),
                   key=lambda g: abs((g[2] - start).total_seconds()), default=None)
        if not game or game[0] in by_id:
            continue
        src, dst = os.path.join(args.out, rid + '.json'), os.path.join(args.out, game[0] + '.json')
        with open(src, encoding='utf-8') as fh:
            rep = json.load(fh)
        rep['id'], rep['game'] = game[0], game[0]
        with open(dst, 'w', encoding='utf-8') as fh:
            json.dump(rep, fh, ensure_ascii=False, separators=(',', ':'))
        os.remove(src)
        del by_id[rid]
        by_id[game[0]] = dict(r, id=game[0], game=game[0])
        for d in done.values():
            d['ids'] = [game[0] if x == rid else x for x in d.get('ids', [])]
        print(f'  ~ linked {rid} -> game {game[0]}')
        changed += 1
    index['replays'] = sorted(by_id.values(), key=lambda r: r['start_utc'])
    with open(idx_path, 'w', encoding='utf-8') as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    print(f'{changed} replay(s) written; {len(index["replays"])} in total')


if __name__ == '__main__':
    main()
