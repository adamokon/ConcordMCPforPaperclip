"""Integration and adversarial unit tests for merge_intervals, validate_interval, and CONTRACT."""

import collections
import random
import unittest

from contract import CONTRACT
from intervals import merge_intervals, validate_interval
from reply import REPLY


class SubList(list):
    """Custom subclass of list for testing container polymorphism."""
    pass


class SubTuple(tuple):
    """Custom subclass of tuple for testing container polymorphism."""
    pass


class CustomNonSequenceIterable:
    """An iterable object that is neither a list nor a tuple."""

    def __init__(self, items):
        self._items = items

    def __iter__(self):
        return iter(self._items)


class TestContractSpecification(unittest.TestCase):
    """Tests covering the CONTRACT schema, policies, and all specified cases."""

    def test_contract_metadata_and_policy(self):
        """Verify the agreed specification constants in CONTRACT."""
        self.assertEqual(CONTRACT["touching"], "merge")
        self.assertEqual(CONTRACT["empty"], "discard")
        self.assertEqual(CONTRACT["output"], "sorted_list_of_tuples")
        self.assertIn("answer", CONTRACT)
        self.assertIn("cases", CONTRACT)

    def test_reply_metadata(self):
        """Verify the public interface decisions in REPLY."""
        self.assertEqual(REPLY["outer_collection"]["accepted_types"], ["list", "tuple"])
        self.assertTrue(REPLY["outer_collection"]["subclasses_accepted"])
        self.assertFalse(REPLY["outer_collection"]["arbitrary_iterables_accepted"])
        self.assertEqual(REPLY["invalid_outer_exception"], "TypeError")
        self.assertFalse(REPLY["mutation"]["outer_collection_mutated"])
        self.assertFalse(REPLY["mutation"]["elements_mutated"])
        self.assertTrue(REPLY["mutation"]["unchanged_on_validation_failure"])
        self.assertTrue(REPLY["mutation"]["result_is_fresh_list"])
        self.assertEqual(REPLY["mutation"]["result_element_type"], "tuple")

    def test_all_contract_cases(self):
        """Verify that every test case defined in CONTRACT['cases'] passes against merge_intervals."""
        self.assertGreater(len(CONTRACT["cases"]), 0)
        for idx, case in enumerate(CONTRACT["cases"]):
            with self.subTest(case_index=idx, input=case["input"]):
                actual = merge_intervals(case["input"])
                self.assertEqual(actual, case["expected"])
                self.assertIsInstance(actual, list)
                self.assertEqual(type(actual), list)
                for item in actual:
                    self.assertEqual(type(item), tuple)

    def test_exact_codex_contract_examples(self):
        """Verify the 5 canonical examples explicitly negotiated with Codex."""
        # [(1, 3), (3, 5)] -> [(1, 5)]
        self.assertEqual(merge_intervals([(1, 3), (3, 5)]), [(1, 5)])
        # [(2, 2)] -> []
        self.assertEqual(merge_intervals([(2, 2)]), [])
        # [(1, 5), (2, 2)] -> [(1, 5)]
        self.assertEqual(merge_intervals([(1, 5), (2, 2)]), [(1, 5)])
        # [(1, 3), (3, 3), (3, 5)] -> [(1, 5)]
        self.assertEqual(merge_intervals([(1, 3), (3, 3), (3, 5)]), [(1, 5)])
        # [(2, 2), (2, 2)] -> []
        self.assertEqual(merge_intervals([(2, 2), (2, 2)]), [])


class TestValidateInterval(unittest.TestCase):
    """Detailed unit tests for validate_interval."""

    def test_valid_tuples_and_lists(self):
        """Valid intervals return a 2-tuple of endpoints."""
        self.assertEqual(validate_interval((0, 0)), (0, 0))
        self.assertEqual(validate_interval((0, 10)), (0, 10))
        self.assertEqual(validate_interval((5, 5)), (5, 5))
        self.assertEqual(validate_interval((100, 250)), (100, 250))
        self.assertEqual(validate_interval([0, 0]), (0, 0))
        self.assertEqual(validate_interval([10, 20]), (10, 20))
        # Ensure returned object is always tuple
        res = validate_interval([3, 7])
        self.assertEqual(type(res), tuple)
        self.assertEqual(res, (3, 7))

    def test_subclasses_accepted_by_validate_interval(self):
        """List and tuple subclasses are accepted as interval containers."""
        sub_list = SubList([4, 9])
        sub_tuple = SubTuple((4, 9))
        self.assertEqual(validate_interval(sub_list), (4, 9))
        self.assertEqual(validate_interval(sub_tuple), (4, 9))
        self.assertEqual(type(validate_interval(sub_list)), tuple)
        self.assertEqual(type(validate_interval(sub_tuple)), tuple)

    def test_invalid_container_types_raise_type_error(self):
        """Non-list/tuple containers raise TypeError in validate_interval."""
        invalid_containers = [
            None,
            123,
            12.34,
            "12",
            b"12",
            bytearray(b"12"),
            {1, 2},
            frozenset([1, 2]),
            {1: 2},
            range(1, 3),
            iter([1, 2]),
            (x for x in (1, 2)),
            CustomNonSequenceIterable([1, 2]),
        ]
        for item in invalid_containers:
            with self.subTest(container=item):
                with self.assertRaises(TypeError):
                    validate_interval(item)

    def test_invalid_length_raises_value_error(self):
        """Containers with length != 2 raise ValueError."""
        invalid_lengths = [
            (),
            (1,),
            (1, 2, 3),
            (1, 2, 3, 4),
            [],
            [1],
            [1, 2, 3],
            [1, 2, 3, 4, 5],
        ]
        for item in invalid_lengths:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    validate_interval(item)

    def test_endpoint_types_raise_type_error(self):
        """Endpoints that are not ints or are bools raise TypeError."""
        invalid_endpoints = [
            (True, 2),
            (1, False),
            (True, True),
            (False, False),
            [False, 10],
            [10, True],
            (1.0, 2),
            (1, 2.5),
            [1.5, 3.5],
            ("1", 2),
            (1, "2"),
            ("a", "b"),
            (None, 2),
            (1, None),
            (None, None),
            ([1], 2),
            (1, [2]),
            ((1,), 2),
            (1, (2,)),
            (1 + 0j, 2),
            (1, object()),
        ]
        for item in invalid_endpoints:
            with self.subTest(item=item):
                with self.assertRaises(TypeError):
                    validate_interval(item)

    def test_negative_endpoints_raise_value_error(self):
        """Negative endpoint values raise ValueError."""
        negative_cases = [
            (-1, 0),
            (0, -1),
            (-5, -5),
            (-10, -2),
            (-1, 10),
            (10, -1),
            [-5, 5],
            [5, -5],
            [-1, -1],
        ]
        for item in negative_cases:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    validate_interval(item)

    def test_reversed_endpoints_raise_value_error(self):
        """Endpoints with start > end raise ValueError."""
        reversed_cases = [
            (1, 0),
            (5, 4),
            (100, 50),
            (10, 9),
            [2, 1],
            [1000, 1],
        ]
        for item in reversed_cases:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    validate_interval(item)

    def test_large_integers(self):
        """Arbitrary large integers are supported."""
        large_a = 10**30
        large_b = 10**30 + 1000
        self.assertEqual(validate_interval((large_a, large_b)), (large_a, large_b))
        self.assertEqual(validate_interval([large_a, large_a]), (large_a, large_a))


class TestMergeIntervalsOuterTypes(unittest.TestCase):
    """Tests covering Codex's explicit list-or-tuple outer interface decision."""

    def test_accepted_outer_list_and_tuple(self):
        """Standard list and tuple outer containers are accepted."""
        self.assertEqual(merge_intervals([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(merge_intervals(((1, 3), (3, 5))), [(1, 5)])
        self.assertEqual(merge_intervals([]), [])
        self.assertEqual(merge_intervals(()), [])

    def test_accepted_outer_subclasses(self):
        """Subclasses of list and tuple are accepted via isinstance."""
        sub_list = SubList([(1, 4), (4, 7)])
        sub_tuple = SubTuple([(2, 5), (5, 8)])
        self.assertEqual(merge_intervals(sub_list), [(1, 7)])
        self.assertEqual(merge_intervals(sub_tuple), [(2, 8)])

        empty_sub_list = SubList()
        empty_sub_tuple = SubTuple()
        self.assertEqual(merge_intervals(empty_sub_list), [])
        self.assertEqual(merge_intervals(empty_sub_tuple), [])

        NamedPair = collections.namedtuple("NamedPair", ["first", "second"])
        named_intervals = NamedPair((1, 3), (3, 6))
        self.assertEqual(merge_intervals(named_intervals), [(1, 6)])

    def test_rejected_outer_types_raise_type_error(self):
        """Arbitrary sequences and iterables raise TypeError, even when empty."""
        rejected_inputs = [
            None,
            # Generators
            (x for x in []),
            (x for x in [(1, 3)]),
            # Iterators
            iter([]),
            iter([(1, 3)]),
            # Sets
            set(),
            {(1, 3)},
            # Frozensets
            frozenset(),
            frozenset([(1, 3)]),
            # Mappings
            {},
            {(1, 3): "val"},
            # Strings
            "",
            "[(1, 3)]",
            # Bytes
            b"",
            b"[(1, 3)]",
            # Bytearray
            bytearray(),
            bytearray(b"[1, 3]"),
            # Range
            range(0),
            range(1, 10),
            # Primitives
            123,
            45.67,
            True,
            False,
            object(),
            # Custom iterables
            CustomNonSequenceIterable([]),
            CustomNonSequenceIterable([(1, 3)]),
        ]
        for rejected in rejected_inputs:
            with self.subTest(rejected_type=type(rejected), value=repr(rejected)):
                with self.assertRaises(TypeError):
                    merge_intervals(rejected)


class TestMergeIntervalsElementValidationAndOrder(unittest.TestCase):
    """Tests covering inner element validation and strict input-order validation."""

    def test_various_inner_container_types(self):
        """Lists, tuples, and subclasses inside the outer collection are accepted."""
        # Inner lists
        self.assertEqual(merge_intervals([[1, 3], [3, 5]]), [(1, 5)])
        # Inner tuples
        self.assertEqual(merge_intervals([(1, 3), (3, 5)]), [(1, 5)])
        # Mixed inner containers
        self.assertEqual(merge_intervals([(1, 3), [3, 5]]), [(1, 5)])
        # Inner subclasses
        self.assertEqual(
            merge_intervals([SubList([1, 4]), SubTuple((4, 7))]),
            [(1, 7)]
        )

    def test_invalid_inner_container_types_raise_type_error(self):
        """Non list/tuple elements raise TypeError."""
        invalid_elements = [
            [(1, 3), None],
            [None],
            [(1, 3), {3, 5}],
            [(1, 3), "35"],
            [(1, 3), 35],
            [(1, 3), (x for x in (3, 5))],
        ]
        for inp in invalid_elements:
            with self.subTest(inp=inp):
                with self.assertRaises(TypeError):
                    merge_intervals(inp)

    def test_invalid_elements_following_empty_intervals(self):
        """Validation raises on the first invalid element, even after empty intervals."""
        # Empty followed by reversed range (ValueError)
        with self.assertRaises(ValueError):
            merge_intervals([(0, 0), (5, 2)])
        with self.assertRaises(ValueError):
            merge_intervals([(3, 3), (10, 1)])

        # Empty followed by negative range (ValueError)
        with self.assertRaises(ValueError):
            merge_intervals([(0, 0), (-1, 5)])
        with self.assertRaises(ValueError):
            merge_intervals([(2, 2), (5, -2)])

        # Empty followed by wrong length (ValueError)
        with self.assertRaises(ValueError):
            merge_intervals([(0, 0), (1, 2, 3)])
        with self.assertRaises(ValueError):
            merge_intervals([(0, 0), ()])
        with self.assertRaises(ValueError):
            merge_intervals([(1, 1), [5]])

        # Empty followed by boolean endpoint (TypeError)
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), (True, 5)])
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), (1, False)])

        # Empty followed by float endpoint (TypeError)
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), (1.5, 5)])
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), (1, 5.0)])

        # Empty followed by non-container (TypeError)
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), None])
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), "invalid"])
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), {1, 2}])

        # Multiple empty intervals before the invalid element
        with self.assertRaises(ValueError):
            merge_intervals([(0, 0), (1, 1), (2, 2), (10, 5)])
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), (1, 1), (2, 2), (1, "a")])

    def test_input_order_error_dispatch(self):
        """The exception raised matches the FIRST invalid element in input order."""
        # Index 0 is TypeError, index 1 is ValueError -> raises TypeError
        with self.assertRaises(TypeError):
            merge_intervals([(1, "a"), (5, 2)])

        # Index 0 is ValueError, index 1 is TypeError -> raises ValueError
        with self.assertRaises(ValueError):
            merge_intervals([(5, 2), (1, "a")])

        # Empty prefix, then TypeError, then ValueError -> raises TypeError
        with self.assertRaises(TypeError):
            merge_intervals([(0, 0), (1, "a"), (5, 2)])

        # Empty prefix, then ValueError, then TypeError -> raises ValueError
        with self.assertRaises(ValueError):
            merge_intervals([(0, 0), (5, 2), (1, "a")])


class TestMergeIntervalsNonMutation(unittest.TestCase):
    """Tests guaranteeing nonmutation of outer collections and inner elements."""

    def test_non_mutation_on_success(self):
        """Input list, tuple, and inner mutable lists are unmodified on success."""
        e1 = [10, 15]
        e2 = [1, 5]
        e3 = [3, 7]
        orig_list = [e1, e2, e3]
        orig_list_copy = list(orig_list)

        result = merge_intervals(orig_list)

        # Outer list unchanged
        self.assertEqual(orig_list, orig_list_copy)
        self.assertEqual(orig_list[0], [10, 15])
        self.assertEqual(orig_list[1], [1, 5])
        self.assertEqual(orig_list[2], [3, 7])

        # Inner list elements unchanged
        self.assertEqual(e1, [10, 15])
        self.assertEqual(e2, [1, 5])
        self.assertEqual(e3, [3, 7])

        # Result is a fresh list
        self.assertIsNot(result, orig_list)
        self.assertEqual(type(result), list)

        # Result elements are tuples, not input list objects
        for item in result:
            self.assertEqual(type(item), tuple)
            self.assertIsNot(item, e1)
            self.assertIsNot(item, e2)
            self.assertIsNot(item, e3)

    def test_non_mutation_on_failure(self):
        """Inputs remain unmutated when validation fails midway."""
        e1 = [0, 0]
        e2 = [1, 5]
        e3 = [10, 2]  # Invalid: start > end
        orig_list = [e1, e2, e3]

        with self.assertRaises(ValueError):
            merge_intervals(orig_list)

        # Ensure original list and elements are completely intact
        self.assertEqual(orig_list, [[0, 0], [1, 5], [10, 2]])
        self.assertEqual(e1, [0, 0])
        self.assertEqual(e2, [1, 5])
        self.assertEqual(e3, [10, 2])

        # Test failure on TypeError
        e4 = [2, 8]
        e5 = "not an interval"
        type_list = [e4, e5]

        with self.assertRaises(TypeError):
            merge_intervals(type_list)

        self.assertEqual(type_list, [[2, 8], "not an interval"])
        self.assertEqual(e4, [2, 8])


class TestMergeIntervalsCanonicalOutputAndIdempotence(unittest.TestCase):
    """Tests verifying canonical output formatting and idempotence."""

    def _assert_canonical_properties(self, result):
        """Helper to assert strict canonical requirements on merge_intervals output."""
        self.assertEqual(type(result), list)
        for i, item in enumerate(result):
            self.assertEqual(type(item), tuple)
            self.assertEqual(len(item), 2)
            start, end = item
            self.assertIsInstance(start, int)
            self.assertNotIsInstance(start, bool)
            self.assertIsInstance(end, int)
            self.assertNotIsInstance(end, bool)
            self.assertGreaterEqual(start, 0)
            self.assertLess(start, end)  # Strictly positive length

            if i > 0:
                prev_start, prev_end = result[i - 1]
                # Strictly ascending starts
                self.assertLess(prev_start, start)
                # Strictly disjoint consecutive intervals (end_i < start_{i+1})
                self.assertLess(prev_end, start)

    def test_all_empty_and_empty_inputs_produce_empty_list(self):
        """Empty inputs or collections containing only empty intervals return []."""
        empty_cases = [
            [],
            (),
            SubList(),
            SubTuple(),
            [(0, 0)],
            [(5, 5)],
            [(0, 0), (1, 1), (2, 2)],
            [(10, 10), (100, 100), (50, 50)],
            [[0, 0], [1, 1]],
        ]
        for case in empty_cases:
            with self.subTest(case=case):
                res = merge_intervals(case)
                self.assertEqual(res, [])
                self.assertEqual(type(res), list)

    def test_canonical_invariants_on_diverse_inputs(self):
        """All valid merge outputs strictly adhere to canonical invariants."""
        inputs = [
            [(1, 3), (3, 5)],
            [(10, 20), (5, 8), (1, 3)],
            [(1, 10), (2, 5), (8, 12)],
            [(0, 0), (1, 4), (4, 4), (4, 9), (9, 9)],
            [(100, 200), (0, 50), (40, 70), (150, 250)],
        ]
        for inp in inputs:
            with self.subTest(inp=inp):
                res = merge_intervals(inp)
                self._assert_canonical_properties(res)

    def test_idempotence(self):
        """Applying merge_intervals to its own output is an identity operation."""
        inputs = [
            [],
            [(1, 3)],
            [(1, 3), (3, 5)],
            [(10, 15), (1, 5), (4, 12)],
            [(0, 0), (5, 5)],
            [(0, 10), (10, 20), (20, 30)],
            [(100, 105), (10, 20), (105, 110), (15, 25), (0, 5), (25, 30)],
        ]
        for inp in inputs:
            with self.subTest(inp=inp):
                res1 = merge_intervals(inp)
                res2 = merge_intervals(res1)
                self.assertEqual(res1, res2)
                self._assert_canonical_properties(res2)


class TestMergeIntervalsAdversarialCases(unittest.TestCase):
    """Adversarial, boundary, and stress tests."""

    def test_duplicate_intervals(self):
        """Duplicate identical intervals collapse into a single interval."""
        self.assertEqual(
            merge_intervals([(2, 6), (2, 6), (2, 6), (2, 6)]),
            [(2, 6)]
        )

    def test_deeply_nested_intervals(self):
        """Contained intervals are absorbed by the enclosing interval."""
        nested = [(0, 100), (10, 90), (20, 80), (30, 70), (40, 60)]
        self.assertEqual(merge_intervals(nested), [(0, 100)])

    def test_scrambled_long_touching_chain(self):
        """A scrambled chain of touching intervals merges into a single range."""
        intervals = [(i, i + 1) for i in range(50)]
        random.Random(1337).shuffle(intervals)
        self.assertEqual(merge_intervals(intervals), [(0, 50)])

    def test_long_disjoint_intervals(self):
        """Disjoint intervals remain separated and are sorted by start endpoint."""
        intervals = [(2 * i, 2 * i + 1) for i in range(50)]
        random.Random(1337).shuffle(intervals)
        expected = [(2 * i, 2 * i + 1) for i in range(50)]
        self.assertEqual(merge_intervals(intervals), expected)

    def test_empty_intervals_at_boundaries_and_throughout(self):
        """Empty intervals at start, middle, and end of clusters are discarded."""
        intervals = [
            (0, 0),
            (0, 3),
            (3, 3),
            (3, 6),
            (6, 6),
            (10, 10),
            (10, 15),
            (15, 15),
        ]
        self.assertEqual(merge_intervals(intervals), [(0, 6), (10, 15)])

    def test_large_coordinate_values(self):
        """Huge integers (beyond 64-bit limits) are handled correctly."""
        base = 10**60
        intervals = [
            (base + 50, base + 80),
            (base, base + 30),
            (base + 20, base + 50),
            (base + 100, base + 120),
            (base + 10, base + 10),  # empty
        ]
        expected = [(base, base + 80), (base + 100, base + 120)]
        self.assertEqual(merge_intervals(intervals), expected)


class TestMergeIntervalsIndependentOracle(unittest.TestCase):
    """Independent oracle comparisons using set-theoretic point union."""

    @staticmethod
    def _point_set_oracle(intervals):
        """Independent reference implementation: computes integer point union."""
        points = set()
        for pair in intervals:
            s, e = pair
            if s < e:
                points.update(range(s, e))
        if not points:
            return []

        sorted_points = sorted(points)
        result = []
        seg_start = sorted_points[0]
        prev = seg_start
        for p in sorted_points[1:]:
            if p == prev + 1:
                prev = p
            else:
                result.append((seg_start, prev + 1))
                seg_start = p
                prev = p
        result.append((seg_start, prev + 1))
        return result

    def test_exhaustive_all_pairs_in_small_domain(self):
        """Exhaustively test all 1-interval and 2-interval combinations over [0, 5]."""
        # All valid half-open intervals with 0 <= start <= end <= 5
        domain_intervals = [
            (a, b)
            for a in range(6)
            for b in range(a, 6)
        ]
        self.assertEqual(len(domain_intervals), 21)

        # Single-interval tests
        for inv in domain_intervals:
            inp = [inv]
            expected = self._point_set_oracle(inp)
            self.assertEqual(merge_intervals(inp), expected)

        # All pairs of intervals: 21 x 21 = 441 tests
        for inv1 in domain_intervals:
            for inv2 in domain_intervals:
                inp = [inv1, inv2]
                expected = self._point_set_oracle(inp)
                actual = merge_intervals(inp)
                self.assertEqual(
                    actual,
                    expected,
                    msg=f"Failed for input: {inp}, expected {expected}, got {actual}"
                )

    def test_generated_random_scenarios(self):
        """Test 100 generated multi-interval scenarios against the point-set oracle."""
        rng = random.Random(42)
        for trial in range(100):
            num_intervals = rng.randint(0, 15)
            inp = []
            for _ in range(num_intervals):
                a = rng.randint(0, 25)
                b = rng.randint(0, 25)
                start, end = min(a, b), max(a, b)
                # Randomly use list or tuple
                inp.append([start, end] if rng.choice([True, False]) else (start, end))

            expected = self._point_set_oracle(inp)
            actual = merge_intervals(inp)
            self.assertEqual(
                actual,
                expected,
                msg=f"Trial {trial} failed on input {inp}: expected {expected}, got {actual}"
            )


if __name__ == "__main__":
    unittest.main()
