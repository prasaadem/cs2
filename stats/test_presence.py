"""Tests for stats/presence.py. Run: python stats/test_presence.py

The log lines below follow the CS2 server log format; the first daily run on real logs
is the real check of the "connected" and "entered the game" wording.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import presence  # noqa: E402


def line(hms, msg, date='11/04/2026'):
    return f'L {date} - {hms}: {msg}\n'


def who(name, sid, team=''):
    return f'"{name}<2><[U:1:{sid}]><{team}>"'


def connect(hms, name, sid, date='11/04/2026'):
    return line(hms, f'{who(name, sid)} connected, address "203.0.113.9:27005"', date)


def enter(hms, name, sid, date='11/04/2026'):
    return line(hms, f'{who(name, sid)} entered the game', date)


def leave(hms, name, sid, reason='NETWORK_DISCONNECT_DISCONNECT_BY_USER', team='CT', date='11/04/2026'):
    return line(hms, f'{who(name, sid, team)} disconnected (reason "{reason}")', date)


def write_logs(folder, name, lines):
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.writelines(lines)
    return path


class PresenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = os.path.join(self.tmp.name, 'logs')
        os.makedirs(self.logs)

    def sessions(self):
        nights = presence.parse_presence(self.logs)
        return [s for night in sorted(nights) for s in nights[night]]

    def test_join_and_leave(self):
        write_logs(self.logs, 'a.log', [
            line('20:00:00', 'Log file started'),
            connect('20:15:03', 'Rat', '111'),
            enter('20:15:20', 'Rat', '111'),
            leave('21:40:10', 'Rat', '111'),
        ])
        (s,) = self.sessions()
        self.assertEqual((s['id'], s['n']), ('111', 'Rat'))
        # the stay starts at "connected", and the times are UTC as in the logs
        self.assertEqual((s['in'], s['out']), ('2026-11-04T20:15:03Z', '2026-11-04T21:40:10Z'))
        self.assertEqual(s['r'], 'NETWORK_DISCONNECT_DISCONNECT_BY_USER')
        self.assertNotIn('o', s)

    def test_ip_address_is_never_stored(self):
        write_logs(self.logs, 'a.log', [connect('20:00:00', 'Rat', '111'), leave('20:30:00', 'Rat', '111')])
        self.assertNotIn('203.0.113.9', json.dumps(presence.parse_presence(self.logs)))

    def test_map_change_rejoin_is_one_stay(self):
        write_logs(self.logs, 'a.log', [
            enter('20:00:00', 'Rat', '111'),
            leave('20:30:00', 'Rat', '111', reason='NETWORK_DISCONNECT_LOOPDEACTIVATE'),
        ])
        write_logs(self.logs, 'b.log', [
            enter('20:30:25', 'Rat', '111'),
            leave('21:00:00', 'Rat', '111'),
        ])
        (s,) = self.sessions()
        self.assertEqual((s['in'], s['out']), ('2026-11-04T20:00:00Z', '2026-11-04T21:00:00Z'))
        self.assertEqual(s['r'], 'NETWORK_DISCONNECT_DISCONNECT_BY_USER')

    def test_real_gap_stays_two_stays(self):
        write_logs(self.logs, 'a.log', [
            enter('20:00:00', 'Rat', '111'), leave('20:30:00', 'Rat', '111'),
            enter('21:10:00', 'Rat', '111'), leave('21:50:00', 'Rat', '111'),
        ])
        self.assertEqual(len(self.sessions()), 2)

    def test_still_connected_at_log_end_is_flagged(self):
        write_logs(self.logs, 'a.log', [
            enter('20:00:00', 'Rat', '111'),
            line('20:45:00', 'World triggered "Round_Start"'),
        ])
        (s,) = self.sessions()
        self.assertEqual(s['out'], '2026-11-04T20:45:00Z')
        self.assertEqual(s['o'], 1)

    def test_log_that_starts_mid_stay(self):
        write_logs(self.logs, 'a.log', [
            line('20:00:00', 'Log file started'),
            leave('20:20:00', 'Rat', '111'),
        ])
        (s,) = self.sessions()
        self.assertEqual(s['in'], '2026-11-04T20:00:00Z')
        self.assertEqual(s['s'], 1)

    def test_bots_are_ignored(self):
        write_logs(self.logs, 'a.log', [
            line('20:00:00', '"Bot<3><BOT><CT>" disconnected (reason "x")'),
            enter('20:01:00', 'Rat', '111'),
            leave('20:10:00', 'Rat', '111'),
        ])
        self.assertEqual([s['id'] for s in self.sessions()], ['111'])

    def test_night_runs_past_midnight(self):
        # 03:30 UTC Nov 5 is 8:30 PM Pacific on Nov 4
        write_logs(self.logs, 'a.log', [
            enter('03:30:00', 'Rat', '111', date='11/05/2026'),
            leave('09:30:00', 'Rat', '111', date='11/05/2026'),
        ])
        self.assertEqual(list(presence.parse_presence(self.logs)), ['2026-11-04'])


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, 'presence')

    @staticmethod
    def s(sid, a, b, **kw):
        return {'id': sid, 'n': 'p' + sid, 'in': f'2026-11-04T{a}Z', 'out': f'2026-11-04T{b}Z', 'r': '', **kw}

    def test_rerun_with_same_logs_changes_nothing(self):
        nights = {'2026-11-04': [self.s('1', '20:00:00', '21:00:00')]}
        self.assertEqual(presence.merge_archive(nights, self.dir), ['2026-11-04'])
        self.assertEqual(presence.merge_archive(nights, self.dir), [])

    def test_nothing_is_ever_removed(self):
        presence.merge_archive({'2026-11-04': [self.s('1', '20:00:00', '21:00:00'),
                                               self.s('2', '20:10:00', '20:50:00')]}, self.dir)
        # DatHost dropped the old log: only a later stay is in the new parse
        presence.merge_archive({'2026-11-04': [self.s('3', '22:00:00', '22:30:00')]}, self.dir)
        ids = sorted(s['id'] for s in presence.load_all(self.dir)['2026-11-04'])
        self.assertEqual(ids, ['1', '2', '3'])

    def test_open_stay_is_closed_by_a_later_run(self):
        presence.merge_archive({'2026-11-04': [self.s('1', '20:00:00', '20:45:00', o=1)]}, self.dir)
        presence.merge_archive({'2026-11-04': [self.s('1', '20:00:00', '21:30:00', r='QUIT')]}, self.dir)
        (s,) = presence.load_all(self.dir)['2026-11-04']
        self.assertEqual((s['out'], s['r']), ('2026-11-04T21:30:00Z', 'QUIT'))
        self.assertNotIn('o', s)

    def test_merging_is_stable_when_repeated(self):
        rows = [self.s('1', '20:00:00', '20:30:00'), self.s('1', '20:30:30', '21:00:00'),
                self.s('1', '22:00:00', '22:20:00')]
        once = presence.merge_sessions(rows)
        self.assertEqual(presence.merge_sessions(once), once)
        self.assertEqual(len(once), 2)


if __name__ == '__main__':
    unittest.main()
