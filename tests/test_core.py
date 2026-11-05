import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from album_video import *


class CoreTests(unittest.TestCase):
    def track(self, i=1, duration=300):
        return Track(Path(f'{i}.wav'), str(i), Fraction(duration), 44100, 2, 16, False, i, None)

    def test_split_boundaries(self):
        self.assertEqual([len(p) for p in split_album([self.track(i, 300) for i in range(13)])], [7, 6])
        self.assertEqual([len(p) for p in split_album([self.track(i, 300) for i in range(14)])], [7, 7])
        self.assertEqual(len(split_album([self.track(i, 300) for i in range(12)])), 1)
        self.assertEqual(len(split_album([self.track(1, Fraction(3600001, 1000)), self.track(2, 1)])), 2)

    def test_ambiguous_metadata(self):
        self.assertIsNone(automatic_order([self.track(), self.track()]))
        self.assertIsNone(automatic_order([replace(self.track(), number=None)]))
        self.assertEqual([t.number for t in automatic_order([self.track(2), self.track(1)])], [1, 2])
        self.assertIsNone(automatic_order([replace(self.track(), disc=1), self.track(2)]))

    def test_manual_validation(self):
        tracks = [self.track(1), self.track(2)]
        for invalid in [['1', '1'], ['0', '2'], ['a', '2'], ['1'], ['1', '3']]:
            with self.assertRaises(ValueError):
                manual_order(tracks, invalid)
        self.assertEqual([t.number for t in manual_order(tracks, ['2', '1'])], [2, 1])

    def test_floor_cumulative_time(self):
        self.assertEqual(clock(Fraction(59999, 1000)), '00:00:59')
        self.assertEqual(clock(Fraction(60001, 1000)), '00:01:00')
        self.assertEqual(clock(Fraction(3599999, 1000)), '00:59:59')
        self.assertEqual(tag_number('03/13'), 3)


if __name__ == '__main__':
    unittest.main()
