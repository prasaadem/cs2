"""Tests for stats/teamhits.py. Run: python stats/test_teamhits.py"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teamhits  # noqa: E402

# Four players, 2 samples a second. A and B start as T; C and D start as CT. At sample 10
# (5 s in) the sides swap, as at half time.
A, B, C, D = 0, 1, 2, 3


def replay(hits=(), blind=(), s=None, **kw):
    s = s or {
        'a': 'TTTTTTTTTTCCCCCCCCCC',
        'b': 'TTTTTTTTTTCCCCCCCCCC',
        'c': 'CCCCCCCCCCTTTTTTTTTT',
        'd': 'CCCCCCCCCCTTTTTTTTTT',
    }
    return {'game': 'g1', 'hz': 2.0, 'n': 20,
            'players': [{'id': k, 'n': k.upper(), 's': v} for k, v in s.items()],
            'hits': [list(h) for h in hits], 'blind': [list(b) for b in blind], **kw}


def hit(t, att, vic, weapon, dmg=0):
    return (t, att, vic, dmg, 'chest', weapon)


class HitsTest(unittest.TestCase):
    def test_weapon_kinds(self):
        k = teamhits.kind
        self.assertEqual(k('inferno'), teamhits.FIRE_I)
        self.assertEqual(k('molotov'), teamhits.FIRE_I)
        self.assertEqual(k('hegrenade'), teamhits.HE_I)
        self.assertEqual(k('knife'), teamhits.KNIFE_I)
        self.assertEqual(k('knife_t'), teamhits.KNIFE_I)
        self.assertEqual(k('ak47'), teamhits.GUN_I)
        self.assertEqual(k('awp'), teamhits.GUN_I)
        for w in ('world', 'planted_c4', 'flashbang', '', None):
            self.assertIsNone(k(w))

    def test_each_kind_counts_for_the_attacker(self):
        r = replay(hits=[hit(1, A, B, 'knife'), hit(2, A, B, 'inferno'), hit(2.5, A, B, 'inferno'),
                         hit(3, A, B, 'hegrenade'), hit(4, A, B, 'ak47'), hit(4.2, A, B, 'm4a1')])
        out = teamhits.replay_teamhits(r)
        self.assertEqual(out['a'], [0, 0, 2, 1, 1, 2])   # fire x2, he, knife, bullets x2
        self.assertEqual(out['b'], [0, 0, 0, 0, 0, 0])   # the victim is not charged

    def test_enemy_hits_do_not_count(self):
        out = teamhits.replay_teamhits(replay(hits=[hit(1, A, C, 'ak47'), hit(1, C, A, 'knife')]))
        self.assertEqual(sum(sum(v) for v in out.values()), 0)

    def test_self_damage_and_no_attacker_do_not_count(self):
        out = teamhits.replay_teamhits(replay(hits=[hit(1, A, A, 'hegrenade'), hit(1, None, A, 'inferno')]))
        self.assertEqual(sum(sum(v) for v in out.values()), 0)

    def test_teammates_stay_teammates_across_the_swap(self):
        # A and B are both T, then both CT; A and C are enemies the whole game
        out = teamhits.replay_teamhits(replay(hits=[
            hit(2, A, B, 'knife'), hit(7, A, B, 'knife'),
            hit(2, A, C, 'knife'), hit(7, A, C, 'knife')]))
        self.assertEqual(out['a'][teamhits.KNIFE_I], 2)

    def test_side_is_read_at_the_time_of_the_event(self):
        # A moves to the CT side halfway through, so C is an enemy before and a teammate after
        s = {'a': 'T' * 10 + 'C' * 10, 'b': 'T' * 20, 'c': 'C' * 20, 'd': 'C' * 20}
        out = teamhits.replay_teamhits(replay(hits=[hit(2, A, C, 'knife'), hit(7, A, C, 'knife')], s=s))
        self.assertEqual(out['a'][teamhits.KNIFE_I], 1)

    def test_dead_players_are_still_on_their_team(self):
        s = {'a': 'TTTTtttttt' + 'CCCCCCCCCC', 'b': 'TTTTTTTTTT' + 'CCCCCCCCCC',
             'c': 'CCCCCCCCCC' + 'TTTTTTTTTT', 'd': 'CCCCCCCCCC' + 'TTTTTTTTTT'}
        # A died at sample 4 (2 s); fire from A's molotov still burning B at 3 s
        out = teamhits.replay_teamhits(replay(hits=[hit(3, A, B, 'inferno')], s=s))
        self.assertEqual(out['a'][teamhits.FIRE_I], 1)

    def test_thrower_who_left_uses_the_last_known_side(self):
        s = {'a': 'TTTT' + '.' * 16, 'b': 'T' * 20, 'c': 'C' * 20, 'd': 'C' * 20}
        out = teamhits.replay_teamhits(replay(hits=[hit(6, A, B, 'inferno')], s=s))
        self.assertEqual(out['a'][teamhits.FIRE_I], 1)

    def test_unknown_side_is_skipped(self):
        s = {'a': '.' * 20, 'b': 'T' * 20, 'c': 'C' * 20, 'd': 'C' * 20}
        out = teamhits.replay_teamhits(replay(hits=[hit(2, A, B, 'knife')], s=s))
        self.assertEqual(out['a'], [0, 0, 0, 0, 0, 0])


class FlashTest(unittest.TestCase):
    def test_team_flash_counts_with_seconds(self):
        # blind rows are [time, victim, attacker, seconds]
        out = teamhits.replay_teamhits(replay(blind=[(2, B, A, 2.5), (3, B, A, 1.25)]))
        self.assertEqual(out['a'][teamhits.FLASH], 2)
        self.assertEqual(out['a'][teamhits.FLASH_S], 3.8)  # 3.75 rounded to one decimal

    def test_enemy_flash_and_self_flash_do_not_count(self):
        out = teamhits.replay_teamhits(replay(blind=[(2, C, A, 3.0), (2, A, A, 3.0), (2, B, None, 3.0)]))
        self.assertEqual(out['a'][teamhits.FLASH], 0)

    def test_flash_after_the_swap(self):
        out = teamhits.replay_teamhits(replay(blind=[(7, B, A, 1.0), (7, C, A, 1.0)]))  # B is A's teammate, C an enemy
        self.assertEqual(out['a'][teamhits.FLASH], 1)


class CoverageTest(unittest.TestCase):
    def test_every_player_gets_a_row_even_with_nothing(self):
        out = teamhits.replay_teamhits(replay())
        self.assertEqual(sorted(out), ['a', 'b', 'c', 'd'])
        self.assertTrue(all(v == [0, 0, 0, 0, 0, 0] for v in out.values()))

    def test_folder_read_skips_index_and_replays_without_a_game(self):
        with tempfile.TemporaryDirectory() as d:
            for name, rep in (('one.json', replay(hits=[hit(1, A, B, 'knife')])),
                              ('two.json', {**replay(), 'game': None}),
                              ('index.json', {'games': []})):
                with open(os.path.join(d, name), 'w', encoding='utf-8') as fh:
                    json.dump(rep, fh)
            out = teamhits.all_teamhits(d)
        self.assertEqual(list(out), ['g1'])
        self.assertEqual(out['g1']['a'][teamhits.KNIFE_I], 1)


if __name__ == '__main__':
    unittest.main()
