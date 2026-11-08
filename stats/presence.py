"""Who was on the server when: join/leave sessions parsed from the server logs.

Each session is one player's stay on the server:
    {"id": "<steam id>", "n": "<name>", "in": "<UTC>", "out": "<UTC>", "r": "<leave reason>"}
plus "o": 1 when the logs ended with the player still connected (the leave is not known),
and "s": 1 when the logs began mid-stay (the join time is the start of the log).

Only the player's id, name, times and leave reason are kept. The "connected, address"
line carries an IP address; it is matched for its timing and never stored.

Sessions are grouped by night with the same rule as the games (US Pacific, six hours
past midnight still counts as the evening before) and saved as data/presence/<night>.json.
A map change disconnects everybody and they rejoin seconds later, so stays separated by
less than MERGE_GAP seconds are joined into one session.
"""
import datetime as dt
import json
import os
import re

import logparse

LINE = logparse.LINE
P = logparse.P
CONNECT = re.compile(P + r' connected, address')
ENTERED = re.compile(P + r' entered the game')
DISCONNECT = logparse.DISCONNECT

MERGE_GAP = 120  # seconds: a leave followed by a join this soon is one stay (map change, reconnect)
VERSION = 1
FMT = '%Y-%m-%dT%H:%M:%SZ'


def _utc(s):
    return dt.datetime.strptime(s, FMT).replace(tzinfo=dt.timezone.utc)


def night_of(t_utc):
    local = logparse.to_local(t_utc)
    return (local - dt.timedelta(hours=6)).date().isoformat()


def parse_group_sessions(files):
    """Raw sessions from one log group (a header log plus its continuation files)."""
    open_ = {}      # id -> session dict still connected
    done = []
    first = last = None
    for f in files:
        with open(f, encoding='utf-8', errors='replace') as fh:
            for raw in fh:
                m = LINE.match(raw.rstrip('\n'))
                if not m:
                    continue
                mo, d, y, hh, mi, ss, msg = m.groups()
                t = dt.datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss), tzinfo=dt.timezone.utc)
                if first is None:
                    first = t
                last = t
                if 'connected' not in msg and 'entered the game' not in msg:
                    continue
                dc = DISCONNECT.search(msg)
                if dc:
                    name, sid, _team, reason = dc.groups()
                    s = open_.pop(sid, None)
                    if s is None:
                        # the log began while this player was already on
                        s = {'id': sid, 'n': name, 'in': first.strftime(FMT), 's': 1}
                    s['n'] = name
                    s['out'] = t.strftime(FMT)
                    s['r'] = reason or ''
                    done.append(s)
                    continue
                ev = CONNECT.search(msg) or ENTERED.search(msg)
                if ev:
                    name, sid = ev.group(1), ev.group(2)
                    s = open_.get(sid)
                    if s is None:
                        open_[sid] = {'id': sid, 'n': name, 'in': t.strftime(FMT)}
                    else:
                        s['n'] = name  # "entered the game" follows "connected": same stay
    for s in open_.values():
        s['out'] = last.strftime(FMT)
        s['r'] = ''
        s['o'] = 1
        done.append(s)
    return done


def parse_presence(logdir):
    """Merged sessions from every log in logdir, as {night: [session, ...]}."""
    raw = []
    for g in logparse.read_groups(logdir):
        raw.extend(parse_group_sessions(g))
    return by_night(merge_sessions(raw))


def merge_sessions(sessions, gap=MERGE_GAP):
    """Join one player's overlapping or nearly touching stays. Idempotent, so it can be
    run again over sessions that are already merged."""
    per = {}
    for s in sessions:
        per.setdefault(s['id'], []).append(s)
    out = []
    for sid, rows in per.items():
        rows.sort(key=lambda s: (s['in'], s['out']))
        cur = None
        for s in rows:
            if cur is not None and (_utc(s['in']) - _utc(cur['out'])).total_seconds() <= gap:
                if s['out'] >= cur['out']:
                    # the later leave decides how the stay ended
                    cur['out'], cur['r'] = s['out'], s.get('r', '')
                    cur.pop('o', None)
                    if s.get('o'):
                        cur['o'] = 1
                cur['n'] = s['n']
                continue
            cur = dict(s)
            out.append(cur)
    out.sort(key=lambda s: (s['in'], s['id']))
    return out


def by_night(sessions):
    nights = {}
    for s in sessions:
        nights.setdefault(night_of(_utc(s['in'])), []).append(s)
    return nights


def load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def save(path, night, sessions):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump({'night': night, 'v': VERSION, 'sessions': sessions}, fh, ensure_ascii=False,
                  indent=1, sort_keys=True)
        fh.write('\n')
    os.replace(tmp, path)


def merge_archive(nights, data_dir):
    """Fold parsed sessions into data/presence/. Sessions are only ever added or
    extended, never removed, so nights whose logs DatHost has already dropped stay intact.
    Returns the nights that changed."""
    os.makedirs(data_dir, exist_ok=True)
    changed = []
    for night, new in sorted(nights.items()):
        path = os.path.join(data_dir, night + '.json')
        old = load(path)['sessions'] if os.path.exists(path) else []
        merged = merge_sessions(old + new)
        if merged != old:
            save(path, night, merged)
            changed.append(night)
    return changed


def load_all(data_dir):
    """{night: [session, ...]} for every saved night."""
    out = {}
    if not os.path.isdir(data_dir):
        return out
    for f in sorted(os.listdir(data_dir)):
        if f.endswith('.json'):
            d = load(os.path.join(data_dir, f))
            out[d['night']] = d['sessions']
    return out
