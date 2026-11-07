"""Tests for stats/ratings.py. Run: python stats/test_ratings.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratings  # noqa: E402


def player(pid, k, d, r=10, k1=0, k2=0, k3=0, k4=0, k5=0):
    return {'id': pid, 'n': 'p' + pid, 'r': r, 'k': k, 'd': d,
            'k1': k1, 'k2': k2, 'k3': k3, 'k4': k4, 'k5': k5}


def game(gid, *players, night='2026-01-01'):
    return {'id': gid, 'night': night, 'p': list(players)}


class RatingsTest(unittest.TestCase):
    def test_matches_site_formula(self):
        # 20 kills, 10 deaths in 20 rounds: 12 one-kill rounds, 4 two-kill rounds
        t = ratings.compute([game('g', player('1', 20, 10, r=20, k1=12, k2=4))])
        expected = (20 / 20 / 0.679 + 0.7 * 10 / 20 / 0.317 + (12 + 16) / 20 / 1.277) / 2.7
        self.assertAlmostEqual(t['1']['rating'], round(expected, 4))

    def test_career_totals_not_average_of_games(self):
        # a 30-round game outweighs a 10-round game: ratings come from summed totals
        games = [game('a', player('1', 30, 10, r=30, k1=30)), game('b', player('1', 0, 10, r=10))]
        totals = {'r': 40, 'k': 30, 'd': 20, 'k1': 30, 'k2': 0, 'k3': 0, 'k4': 0, 'k5': 0}
        self.assertAlmostEqual(ratings.compute(games)['1']['rating'], round(ratings.hltv_rating(totals), 4))

    def test_game_order_does_not_matter(self):
        games = [game(f'g{i}', player('1', 8 + i, 5, k1=6), player('2', 4, 8, k1=4)) for i in range(6)]
        self.assertEqual(
            {k: v['rating'] for k, v in ratings.compute(games).items()},
            {k: v['rating'] for k, v in ratings.compute(list(reversed(games))).items()},
        )

    def test_flags_and_latest_name(self):
        games = [game(f'g{i:02d}', player('1', 5, 5, k1=5)) for i in range(12)]
        games.append(dict(game('z', player('2', 5, 5, k1=5)), p=[dict(player('1', 5, 5, k1=5), n='renamed'), player('2', 5, 5, k1=5)]))
        t = ratings.compute(games)
        self.assertTrue(t['1']['regular'])
        self.assertTrue(t['2']['provisional'])
        self.assertEqual(t['1']['name'], 'renamed')

    def test_empty_archive(self):
        self.assertEqual(ratings.compute([]), {})


if __name__ == '__main__':
    unittest.main()
