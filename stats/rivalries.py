"""Who killed whom, game by game, for the Rivalries page.

The games carry every kill as a pair (killer, victim) in `kp`, but those lists are big and
live in positions.json for the heatmaps. The Rivalries page only needs how many times each
player killed each opponent in each game, so this boils them down to

    {"ids": [player id, ...], "g": {game id: [[killer, victim, kills], ...]}}

where killer and victim are indexes into `ids`. Kills on a teammate and suicides are left
out, and so are warm-up maps (aim_*, awp_*), the same rules as the Discord recap in
recap.py (which the page's "last night" view is checked against).
"""
from collections import Counter

import recap


def opponent_kills(games):
    """The compact structure described above, built from the games as read from data/games."""
    ids, index = [], {}

    def idx(pid):
        if pid not in index:
            index[pid] = len(ids)
            ids.append(pid)
        return index[pid]

    out = {}
    for g in games:
        if recap.is_warmup(g):
            continue
        team = {p['id']: p.get('team') for p in g['p']}
        n = Counter()
        for k in g.get('kp') or []:
            killer, victim = k[2], k[3]
            if killer != victim and killer in team and victim in team and team[killer] != team[victim]:
                n[(killer, victim)] += 1
        out[g['id']] = [[idx(a), idx(b), c] for (a, b), c in sorted(n.items())]
    return {'ids': ids, 'g': out}
