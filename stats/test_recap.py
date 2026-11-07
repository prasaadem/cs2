"""Tests for stats/recap.py. Run: python stats/test_recap.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recap import build_recap  # noqa: E402


def p(pid, team, res='W'):
    return {'id': pid, 'n': 'p' + pid, 'team': team, 'r': 10, 'res': res}


def kill(killer, victim):
    return [0, 0, killer, victim, 'T', 0, 0, 0, 0, 0, 0, 'ak47', 0]


def game(night, kills, map_name='de_dust2', players=None, fin=True):
    players = players or [p('1', 'A'), p('2', 'A'), p('3', 'B', 'L'), p('4', 'B', 'L')]
    return {'night': night, 'map': map_name, 'fin': fin, 'p': players,
            'kp': [kill(a, b) for a, b in kills]}


class RecapTest(unittest.TestCase):
    def test_only_latest_night_counts(self):
        old = game('2026-11-01', [('3', '1')] * 9)
        new = game('2026-11-04', [('1', '3')] * 4)
        r = build_recap([old, new])
        self.assertEqual(r['night'], '2026-11-04')
        self.assertIn('Nov 4, 1 games', r['text'])
        self.assertIn('- p3: p1 got you **4-0**', r['text'])
        self.assertNotIn('9', r['text'])

    def test_warmup_maps_skipped_even_if_latest(self):
        real = game('2026-11-03', [('1', '3')] * 3)
        warm = game('2026-11-04', [('3', '1')] * 8, map_name='aim_deagle')
        awp = game('2026-11-04', [('3', '1')] * 8, map_name='awp_india_cs2')
        r = build_recap([real, warm, awp])
        self.assertEqual(r['night'], '2026-11-03')
        self.assertIn('p1 got you **3-0**', r['text'])

    def test_mutual_nemesis_on_one_line(self):
        r = build_recap([game('2026-11-04', [('1', '3')] * 5 + [('3', '1')] * 4)])
        self.assertIn("p1 ⇄ p3: **5-4**, each other's nemesis", r['text'])
        r = build_recap([game('2026-11-04', [('1', '3')] * 4 + [('3', '1')] * 4)])
        self.assertIn('**4-4**, dead even', r['text'])

    def test_teamkills_and_small_counts_ignored(self):
        r = build_recap([game('2026-11-04', [('1', '2')] * 6 + [('1', '3')] * 2)])
        self.assertNotIn('Nemesis', r['text'])

    def test_duo_streaks(self):
        games = [game('2026-11-04', [('1', '3')]) for _ in range(3)]
        r = build_recap(games)
        self.assertIn('Unbeaten together: p1 + p2 3-0', r['text'])
        self.assertIn('Never won together: p3 + p4 0-3', r['text'])
        mixed = games[:2] + [game('2026-11-04', [], players=[p('1', 'A', 'L'), p('2', 'A', 'L'), p('3', 'B'), p('4', 'B')])]
        self.assertNotIn('Duos', build_recap(mixed)['text'])

    def test_names_escaped_and_length_capped(self):
        players = [dict(p(str(i), 'A' if i < 10 else 'B'), n=f'*star_{i}*' * 3) for i in range(20)]
        kills = [(str(a), str(b)) for a in range(10) for b in range(10, 20) for _ in range(3)]
        r = build_recap([game('2026-11-04', kills, players=players)])
        self.assertIn('\\*star\\_', r['text'])
        self.assertLessEqual(len(r['text']), 1900)

    def test_nothing_to_report(self):
        self.assertIsNone(build_recap([]))
        self.assertIsNone(build_recap([game('2026-11-04', [], map_name='aim_ak_bench')]))


if __name__ == '__main__':
    unittest.main()
