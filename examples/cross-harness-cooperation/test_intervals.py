"""Run with python3 -B -m unittest or python3 -B test_intervals.py."""

import copy
import itertools
import unittest
from collections import UserList

from intervals import merge_intervals, validate_interval
from reply import REPLY


class ValidateIntervalTests(unittest.TestCase):
    def test_valid_intervals_return_tuples(self):
        for pair in ([0, 1], (2, 7), [0, 0], (5, 5), [0, 10 ** 100]):
            with self.subTest(pair=pair):
                result = validate_interval(pair)
                self.assertIs(type(result), tuple)
                self.assertEqual(result, tuple(pair))

    def test_input_list_is_unchanged(self):
        pair = [3, 8]
        self.assertEqual(validate_interval(pair), (3, 8))
        self.assertEqual(pair, [3, 8])

    def test_wrong_containers_raise_type_error(self):
        for pair in (None, 7, True, "12", b"12", {0, 1},
                     {"start": 0, "end": 1}, iter([0, 1])):
            with self.subTest(pair=pair):
                with self.assertRaises(TypeError):
                    validate_interval(pair)

    def test_wrong_lengths_raise_value_error(self):
        for pair in ([], (), [0], (0,), [0, 1, 2], (0, 1, 2)):
            with self.subTest(pair=pair):
                with self.assertRaises(ValueError):
                    validate_interval(pair)

    def test_noninteger_endpoints_raise_type_error(self):
        for endpoint in (True, False, 1.0, "1", None, [], complex(1, 0)):
            for pair in ([endpoint, 2], [0, endpoint]):
                with self.subTest(pair=pair):
                    with self.assertRaises(TypeError):
                        validate_interval(pair)

    def test_negative_endpoints_raise_value_error(self):
        for pair in ([-1, 2], [0, -1], [-2, -1], [-1, -1]):
            with self.subTest(pair=pair):
                with self.assertRaises(ValueError):
                    validate_interval(pair)

    def test_reversed_intervals_raise_value_error(self):
        for pair in ([1, 0], (8, 3)):
            with self.subTest(pair=pair):
                with self.assertRaises(ValueError):
                    validate_interval(pair)


class MergeIntervalTests(unittest.TestCase):
    def test_contract_examples(self):
        cases = [
            ([(2, 2)], []),
            ([(1, 5), (2, 2)], [(1, 5)]),
            ([(1, 3), (3, 3), (3, 5)], [(1, 5)]),
            ([(2, 2), (2, 2)], []),
            ([(1, 3), (3, 5)], [(1, 5)]),
            ([], []),
            ([(0, 10)], [(0, 10)]),
            ([(1, 3), (5, 8), (10, 12)], [(1, 3), (5, 8), (10, 12)]),
            ([(10, 12), (1, 3), (5, 8)], [(1, 3), (5, 8), (10, 12)]),
            ([(1, 6), (4, 9)], [(1, 9)]),
            ([(1, 10), (3, 7)], [(1, 10)]),
            ([(2, 6)] * 3, [(2, 6)]),
            ([(0, 2), (2, 4), (4, 6), (6, 8), (8, 10)], [(0, 10)]),
            ([(6, 8), (0, 2), (4, 6), (2, 4)], [(0, 8)]),
            ([(0, 0), (5, 5), (1, 3), (10, 10), (4, 7), (2, 2)],
             [(1, 3), (4, 7)]),
            ([(3, 3), (3, 6), (6, 6)], [(3, 6)]),
            ([(12, 16), (1, 4), (0, 0), (3, 7), (10, 12), (7, 9),
              (5, 5), (15, 20), (1, 4)], [(1, 9), (10, 20)]),
            ([(1, 3), (3, 6), (2, 4)], [(1, 6)]),
            ([(100, 105), (10, 20), (105, 110), (15, 25), (0, 5), (25, 30)],
             [(0, 5), (10, 30), (100, 110)]),
            ([(10**18, 10**18 + 10), (10**18 + 10, 10**18 + 20)],
             [(10**18, 10**18 + 20)]),
            ([(0, 0), (1, 1), (2, 2)], []),
            ([(0, 0), (0, 1), (1, 2)], [(0, 2)]),
        ]
        for pairs, expected in cases:
            for outer in (pairs, tuple(pairs)):
                with self.subTest(outer=outer):
                    self.assertEqual(merge_intervals(outer), expected)

    def test_accepted_subclasses_and_mixed_elements(self):
        class ListSubclass(list):
            pass
        class TupleSubclass(tuple):
            pass
        for outer_type in (list, tuple, ListSubclass, TupleSubclass):
            self.assertEqual(merge_intervals(outer_type([
                ListSubclass([3, 5]), TupleSubclass((1, 3)), [8, 9]
            ])), [(1, 5), (8, 9)])

    def test_rejected_outer_types_even_when_empty(self):
        for outer in (None, False, 1, 1.0, "", "12", b"", bytearray(),
                      {}, {"x": (0, 1)}, set(), {(0, 1)}, frozenset(),
                      range(0), range(2), iter([]), iter([(0, 1)]),
                      (pair for pair in []), UserList([])):
            with self.subTest(outer=outer):
                with self.assertRaises(TypeError):
                    merge_intervals(outer)

    def test_rejected_iterator_is_not_consumed(self):
        outer = iter([(0, 1), (1, 2)])
        with self.assertRaises(TypeError):
            merge_intervals(outer)
        self.assertEqual(next(outer), (0, 1))

    def test_invalid_elements_after_empty_or_nonempty_intervals(self):
        invalid_cases = [
            (None, TypeError), (7, TypeError), (True, TypeError),
            ("12", TypeError), (b"12", TypeError), ({0, 1}, TypeError),
            ({"start": 0, "end": 1}, TypeError),
            ([], ValueError), ([0], ValueError), ([0, 1, 2], ValueError),
            ([True, 2], TypeError), ([0, False], TypeError),
            ([1.0, 2], TypeError), ([0, "2"], TypeError),
            ([None, 2], TypeError), ([0, []], TypeError),
            ([-1, 2], ValueError), ([0, -1], ValueError),
            ([-1, -1], ValueError), ([3, 2], ValueError),
        ]
        for invalid, exception in invalid_cases:
            for prefix in ([], [(0, 0)], [(0, 0), (2, 2)], [(0, 10)]):
                pairs = prefix + [invalid, (20, 21)]
                before = copy.deepcopy(pairs)
                with self.subTest(pairs=pairs):
                    with self.assertRaises(exception):
                        merge_intervals(pairs)
                    self.assertEqual(pairs, before)

    def test_validation_raises_first_error_in_input_order(self):
        with self.assertRaises(ValueError):
            merge_intervals([(0, 0), (2, 1), None])
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), None, (2, 1)])

    def test_no_mutation_and_fresh_results(self):
        pairs = [[6, 9], [1, 3], [3, 7], [0, 0]]
        before = copy.deepcopy(pairs)
        identities = [id(pair) for pair in pairs]
        result = merge_intervals(pairs)
        self.assertEqual(pairs, before)
        self.assertEqual([id(pair) for pair in pairs], identities)
        self.assertIsNot(result, pairs)
        result.append((20, 30))
        self.assertEqual(pairs, before)
        self.assertEqual(merge_intervals(pairs), [(1, 9)])
        empty = []
        self.assertIsNot(merge_intervals(empty), empty)
        self.assertIsNot(merge_intervals(empty), merge_intervals(empty))

    def test_unbounded_integer_endpoints(self):
        huge = 10 ** 200
        self.assertEqual(merge_intervals([(huge, huge + 1), (0, huge)]),
                         [(0, huge + 1)])

    def test_exhaustive_small_unions_against_point_set_oracle(self):
        candidates = [(start, end) for start in range(4)
                      for end in range(start, 4)]
        for length in range(4):
            for pairs in itertools.product(candidates, repeat=length):
                with self.subTest(pairs=pairs):
                    points = set().union(*(set(range(a, b)) for a, b in pairs))
                    expected = []
                    for point in sorted(points):
                        if expected and expected[-1][1] == point:
                            expected[-1] = (expected[-1][0], point + 1)
                        else:
                            expected.append((point, point + 1))
                    result = merge_intervals(pairs)
                    self.assertEqual(result, expected)
                    self.assertIs(type(result), list)
                    for start, end in result:
                        self.assertLess(start, end)
                    for pair in result:
                        self.assertIs(type(pair), tuple)
                    for left, right in zip(result, result[1:]):
                        self.assertLess(left[1], right[0])
                    self.assertEqual(merge_intervals(result), result)

    def test_reply_matches_interface(self):
        self.assertIs(type(REPLY), dict)
        self.assertTrue(REPLY["answer"])
        self.assertEqual(REPLY["outer_collection"]["accepted_types"],
                         ["list", "tuple"])
        self.assertTrue(REPLY["outer_collection"]["subclasses_accepted"])
        self.assertFalse(REPLY["outer_collection"]["arbitrary_iterables_accepted"])
        self.assertEqual(REPLY["invalid_outer_exception"], "TypeError")
        self.assertFalse(REPLY["mutation"]["outer_collection_mutated"])
        self.assertFalse(REPLY["mutation"]["elements_mutated"])
        self.assertTrue(REPLY["mutation"]["unchanged_on_validation_failure"])
        self.assertTrue(REPLY["mutation"]["result_is_fresh_list"])
        self.assertEqual(REPLY["mutation"]["result_element_type"], "tuple")


if __name__ == "__main__":
    unittest.main()
