"""Tests for stats/ratings.py. Run: python stats/test_ratings.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ratings  # noqa: E402


def player(pid, team, sides, dmg, k, d, r=10):
    return {'id': pid, 'n': 'p' + pid, 'team': team, 'sd': sides, 'r': r,
            'dmg': dmg, 'k': k, 'd': d, 'ek': 0, 'ed': 0}


def game(gid, winner_ids, loser_ids, strong=None):
    """Ten rounds; the 'A' team wins 8 of them. Players on A get the winners' stats."""
    rounds = 'AAAAAAAABB'
    a = [player(i, 'A', 'AAAAAAAAAA', 900 if i == strong else 700, 12 if i == strong else 8, 6) for i in winner_ids]
    b = [player(i, 'B', 'BBBBBBBBBB', 500, 6, 10) for i in loser_ids]
    return {'id': gid, 'fin': True, 'win': 'A', 'rounds': rounds, 'night': '2026-01-01', 'p': a + b}


class RatingsTest(unittest.TestCase):
    def test_consistent_winner_rates_above_consistent_loser(self):
        games = [game(f'g{i:02d}', ['1', '2'], ['3', '4'], strong='1') for i in range(15)]
        table = ratings.compute(games)
        self.assertGreater(table['1']['rating'], table['2']['rating'])
        self.assertGreater(table['2']['rating'], table['3']['rating'])

    def test_deterministic(self):
        games = [game(f'g{i:02d}', ['1', '2'], ['3', '4']) for i in range(6)]
        self.assertEqual(ratings.compute(games), ratings.compute(games))

    def test_new_player_flagged_provisional(self):
        games = [game(f'g{i:02d}', ['1', '2'], ['3', '4']) for i in range(12)]
        games.append(game('g99', ['1', '5'], ['3', '4']))
        table = ratings.compute(games)
        self.assertTrue(table['5']['provisional'])
        self.assertFalse(table['5']['regular'])
        self.assertTrue(table['1']['regular'])

    def test_short_appearances_and_unfinished_games_ignored(self):
        g = game('g00', ['1', '2'], ['3', '4'])
        g['p'].append(player('9', 'A', 'AAA.......', 100, 1, 1, r=3))
        self.assertNotIn('9', ratings.compute([g]))
        g2 = dict(game('g01', ['1', '2'], ['3', '4']), fin=False)
        self.assertIsNone(ratings.team_results(dict(g2, p=[])))

    def test_empty_archive(self):
        self.assertEqual(ratings.compute([]), {})


if __name__ == '__main__':
    unittest.main()
