"""Independent supervisor checks using a finite point-set oracle, not merge logic."""

import copy
import itertools
import unittest

from intervals import merge_intervals


def point_set_oracle(intervals):
    points = sorted({point for start, end in intervals for point in range(start, end)})
    result = []
    for _, group in itertools.groupby(enumerate(points), lambda item: item[1] - item[0]):
        block = [point for _, point in group]
        result.append((block[0], block[-1] + 1))
    return result


class SupervisorOracleTests(unittest.TestCase):
    def test_all_small_ordered_inputs_up_to_three_intervals(self):
        universe = [(a, b) for a in range(5) for b in range(a, 5)]
        checked = 0
        for size in range(4):
            for values in itertools.product(universe, repeat=size):
                supplied = [list(pair) for pair in values]
                before = copy.deepcopy(supplied)
                expected = point_set_oracle(values)
                actual = merge_intervals(supplied)
                with self.subTest(values=values):
                    self.assertIs(type(actual), list)
                    self.assertEqual(actual, expected)
                    self.assertTrue(all(type(pair) is tuple for pair in actual))
                    self.assertEqual(merge_intervals(actual), actual)
                    self.assertEqual(supplied, before)
                checked += 1
        self.assertEqual(checked, 3616)

    def test_huge_coordinates_do_not_require_point_enumeration(self):
        base = 10 ** 100
        self.assertEqual(merge_intervals([(base + 20, base + 30), (base, base + 10),
                                         (base + 10, base + 20), (base + 5, base + 5)]),
                         [(base, base + 30)])


if __name__ == '__main__':
    unittest.main()
