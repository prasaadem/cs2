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
        else:
            t_land = int(rows['tick'].iloc[-1])         # molotov / HE / flash projectiles end where they go off
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
    shots_all = [(int(e['tick']), str(e.get('user_steamid') or ''))
                 for e in events(p, 'weapon_fire') if not str(e.get('weapon', '')).endswith(NOT_GUNS)]
    # a match begins at the server's restart/new-match events; otherwise the whole demo is one match
    starts = sorted({int(e['tick']) for n in ('begin_new_match', 'round_announce_match_start') for e in events(p, n)})
    ticks = p.parse_ticks(['X', 'Y', 'yaw', 'is_alive', 'team_num'])
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
        for sid, rows in seg.groupby('steamid'):
            if not sid or str(sid) == '0':
                continue  # GOTV itself
            idx = ((rows['tick'] - a) // SAMPLE_TICKS).astype(int).tolist()
            xs, ys, as_, ss = [0] * n, [0] * n, [0] * n, ['.'] * n
            lx = ly = 0
            for i, x, y, yaw, alive, team in zip(idx, rows['X'], rows['Y'], rows['yaw'], rows['is_alive'], rows['team_num']):
                side = SIDE.get(int(num(team, 0)))
                if not side:
                    continue  # spectator / unassigned
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
            players.append({'id': pid, 'n': str(rows['name'].iloc[-1]), 'x': delta(xs), 'y': delta(ys), 'a': as_, 's': ''.join(ss)})
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
        kills = []
        for e in deaths:
            tk = int(e['tick'])
            if not a <= tk < b or num(e.get('user_X')) is None:
                continue
            acc = lambda k: str(int(e[k]) - 76561197960265728) if num(e.get(k)) and int(e[k]) > 76561197960265728 else None  # noqa: E731
            kills.append([sec(tk), acc('attacker_steamid'), acc('user_steamid'), str(e.get('weapon') or ''),
                          1 if e.get('headshot') else 0,
                          int(num(e.get('attacker_X'), num(e.get('user_X')))), int(num(e.get('attacker_Y'), num(e.get('user_Y')))),
                          int(num(e.get('user_X'))), int(num(e.get('user_Y')))])
        acct = lambda sid: str(int(sid) - 76561197960265728) if sid and sid.isdigit() and int(sid) > 76561197960265728 else None  # noqa: E731
        nades = []
        for kind, sid, t_throw, t_land, t_end, path in grenades:
            if not a <= t_throw < b:
                continue
            flat = [c for xy in path for c in xy]
            nades.append([kind, acct(sid), sec(t_throw), sec(t_land), sec(t_end),
                          [v for pair in zip(delta(flat[0::2]), delta(flat[1::2])) for v in pair]])
        pidx = {pl['id']: i for i, pl in enumerate(players)}
        shots = [[sec(tk), pidx[acct(sid)]] for tk, sid in shots_all if a <= tk < b and acct(sid) in pidx]
        start = t0 + dt.timedelta(seconds=a / TICKRATE)
        game = min((g for g in games if g[1] == mp and abs((g[2] - start).total_seconds()) <= MATCH_WINDOW),
                   key=lambda g: abs((g[2] - start).total_seconds()), default=None)
        rid = game[0] if game else start.strftime('%Y%m%d-%H%M') + '-' + mp
        out.append({'id': rid, 'game': game[0] if game else None, 'map': mp,
                    'start_utc': start.strftime('%Y-%m-%dT%H:%M:%SZ'), 'hz': TICKRATE / SAMPLE_TICKS, 'n': n,
                    'players': players, 'rounds': rounds, 'kills': kills, 'grenades': nades, 'shots': shots})
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
