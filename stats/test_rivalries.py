"""Tests for stats/rivalries.py. Run: python stats/test_rivalries.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rivalries  # noqa: E402


def game(gid, kp, map_='de_dust2', teams=None):
    teams = teams or {'A': 'CT', 'B': 'T', 'C': 'CT'}
    return {'id': gid, 'map': map_, 'p': [{'id': i, 'team': t} for i, t in teams.items()],
            'kp': [[1, 0, k, v, 'CT', 'ak47', 0] for k, v in kp]}


class OpponentKillsTest(unittest.TestCase):
    def counts(self, out, gid):
        ids = out['ids']
        return {(ids[a], ids[b]): c for a, b, c in out['g'][gid]}

    def test_counts_kills_per_pair(self):
        out = rivalries.opponent_kills([game('g1', [('A', 'B'), ('A', 'B'), ('B', 'A')])])
        self.assertEqual(self.counts(out, 'g1'), {('A', 'B'): 2, ('B', 'A'): 1})

    def test_teammate_kills_and_suicides_are_left_out(self):
        out = rivalries.opponent_kills([game('g1', [('A', 'C'), ('A', 'A'), ('B', 'A')])])
        self.assertEqual(self.counts(out, 'g1'), {('B', 'A'): 1})

    def test_warmup_maps_are_skipped(self):
        out = rivalries.opponent_kills([game('g1', [('A', 'B')], map_='aim_map'),
                                        game('g2', [('A', 'B')], map_='awp_lego')])
        self.assertEqual(out['g'], {})

    def test_unknown_players_are_ignored(self):
        out = rivalries.opponent_kills([game('g1', [('Z', 'B')])])
        self.assertEqual(out['g']['g1'], [])

    def test_indexes_are_shared_across_games(self):
        out = rivalries.opponent_kills([game('g1', [('A', 'B')]), game('g2', [('B', 'A')])])
        self.assertEqual(sorted(out['ids']), ['A', 'B'])
        self.assertEqual(self.counts(out, 'g2'), {('B', 'A'): 1})


if __name__ == '__main__':
    unittest.main()
