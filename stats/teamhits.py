"""Same-team contact stats: who lands hits and flashes on their own team.

Friendly fire is off on the server, so none of this hurts anyone. The demo still records
the contact, as a player_hurt with 0 damage and as a blind event for flashes, and those
are what get counted here, from the replay files in docs/data/replays/.

Per player and game the result is
    [team flashes, seconds the teammates were blind, fire, HE, knife, bullets]
where "fire" is molotov / incendiary burning, "HE" an HE grenade, "knife" a knife hit and
"bullets" a gun hit (rifles, pistols, snipers, shotguns, the Zeus).

Teams come from the replay's own per-player samples (players[i].s: C/T while alive, c/t
once dead, "." off the server), looked up at the time of the event. That follows the
half-time swap by itself, with no round numbering to get wrong. A player who left after
throwing something is looked up at their last known side.
"""
import glob
import json
import os

LOOKBACK = 400  # samples (200 s at the usual 2 Hz) to search back for a last known side

FIRE = {'inferno', 'molotov', 'incgrenade'}
HE = {'hegrenade'}
# damage sources that are not a player's weapon, or that carry no contact
SKIP = {'world', 'worldspawn', 'trigger_hurt', 'planted_c4', 'c4', 'flashbang',
        'smokegrenade', 'decoy', 'decoygrenade', 'env_fire', 'fall'}

# slots in the per-player list
FLASH, FLASH_S, FIRE_I, HE_I, KNIFE_I, GUN_I = range(6)


def kind(weapon):
    """FIRE_I / HE_I / KNIFE_I / GUN_I for a hit's weapon, or None when it should not count."""
    w = (weapon or '').lower()
    if not w or w in SKIP:
        return None
    if w in FIRE:
        return FIRE_I
    if w in HE:
        return HE_I
    if w.startswith('knife') or 'bayonet' in w or 'karambit' in w:
        return KNIFE_I
    return GUN_I


def _side_lookup(players, hz):
    def side(i, t):
        if i is None or not 0 <= i < len(players):
            return None
        s = players[i].get('s') or ''
        k = int(t * hz)
        k = max(0, min(len(s) - 1, k))
        for j in range(k, max(-1, k - LOOKBACK), -1):
            if s[j] in 'CTct':
                return s[j].upper()
        return None
    return side


def replay_teamhits(rep):
    """{player id: [flashes, flash seconds, fire, he, knife, bullets]} for one replay.
    Every player in the replay gets a row, zeros included, so a game with no contact still
    counts as covered."""
    players = rep.get('players') or []
    hz = rep.get('hz') or 2.0
    side = _side_lookup(players, hz)
    out = [[0, 0.0, 0, 0, 0, 0] for _ in players]
    for t, att, vic, _dmg, _grp, weapon in rep.get('hits') or []:
        if att is None or att == vic:
            continue
        slot = kind(weapon)
        if slot is None:
            continue
        a, v = side(att, t), side(vic, t)
        if a and a == v and 0 <= att < len(out):
            out[att][slot] += 1
    for t, vic, att, secs in rep.get('blind') or []:
        if att is None or att == vic or not 0 <= att < len(out):
            continue
        a, v = side(att, t), side(vic, t)
        if a and a == v:
            out[att][FLASH] += 1
            out[att][FLASH_S] += secs or 0
    return {p['id']: [row[0], round(row[1], 1), *row[2:]] for p, row in zip(players, out)}


def all_teamhits(replay_dir):
    """{game id: {player id: [...]}} for every replay that belongs to a known game."""
    out = {}
    for path in sorted(glob.glob(os.path.join(replay_dir, '*.json'))):
        if os.path.basename(path) == 'index.json':
            continue
        with open(path, encoding='utf-8') as fh:
            rep = json.load(fh)
        gid = rep.get('game')
        if gid:
            out[gid] = replay_teamhits(rep)
    return out
