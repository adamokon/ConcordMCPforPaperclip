"""Specification contract for merge_intervals helper."""

CONTRACT = {
    "touching": "merge",
    "empty": "discard",
    "output": "sorted_list_of_tuples",
    "answer": (
        "We specify the following deterministic canonical output policy for merge_intervals:\n\n"
        "1. Touching intervals: MERGE.\n"
        "   For integer half-open intervals [a, b) and [b, c), the boundary point b is excluded by "
        "   the lower interval and included by the upper interval. Together they cover [a, c) without "
        "   any gap. Therefore, touching intervals must be merged into a single contiguous interval. "
        "   Specifically, [(1, 3), (3, 5)] becomes [(1, 5)].\n\n"
        "2. Empty intervals: DISCARD.\n"
        "   An empty half-open interval [a, a) contains zero integer points (the empty set). Under "
        "   standard set union semantics, empty sets contribute no elements to the union. Discarding "
        "   empty intervals ensures a unique, minimal, and non-redundant canonical representation. "
        "   If the input contains only empty intervals (or is empty), the output is an empty list [].\n\n"
        "3. Exact outputs for the requested examples:\n"
        "   - [(2, 2)] -> []\n"
        "   - [(1, 5), (2, 2)] -> [(1, 5)]\n"
        "   - [(1, 3), (3, 3), (3, 5)] -> [(1, 5)]\n"
        "   - [(2, 2), (2, 2)] -> []\n"
        "   - [(1, 3), (3, 5)] -> [(1, 5)]\n\n"
        "4. Canonical output format: sorted_list_of_tuples.\n"
        "   The output must be a Python list of 2-tuples (start, end). The list must be sorted in strictly "
        "   ascending order by start endpoint (start_i < start_{i+1}), each interval must have positive "
        "   length (start < end), and consecutive intervals must be strictly disjoint (end_i < start_{i+1})."
    ),
    "cases": [
        # Exact examples requested by Codex
        {
            "input": [(1, 3), (3, 5)],
            "expected": [(1, 5)],
        },
        {
            "input": [(2, 2)],
            "expected": [],
        },
        {
            "input": [(1, 5), (2, 2)],
            "expected": [(1, 5)],
        },
        {
            "input": [(1, 3), (3, 3), (3, 5)],
            "expected": [(1, 5)],
        },
        {
            "input": [(2, 2), (2, 2)],
            "expected": [],
        },
        # Empty input collection
        {
            "input": [],
            "expected": [],
        },
        # Single valid interval
        {
            "input": [(0, 10)],
            "expected": [(0, 10)],
        },
        # Already sorted and disjoint intervals
        {
            "input": [(1, 3), (5, 8), (10, 12)],
            "expected": [(1, 3), (5, 8), (10, 12)],
        },
        # Unsorted disjoint intervals
        {
            "input": [(10, 12), (1, 3), (5, 8)],
            "expected": [(1, 3), (5, 8), (10, 12)],
        },
        # Overlapping intervals
        {
            "input": [(1, 6), (4, 9)],
            "expected": [(1, 9)],
        },
        # Contained interval (subset)
        {
            "input": [(1, 10), (3, 7)],
            "expected": [(1, 10)],
        },
        # Duplicate identical intervals
        {
            "input": [(2, 6), (2, 6), (2, 6)],
            "expected": [(2, 6)],
        },
        # Chain of multiple touching intervals
        {
            "input": [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10)],
            "expected": [(0, 10)],
        },
        # Unsorted chain of touching intervals
        {
            "input": [(6, 8), (0, 2), (4, 6), (2, 4)],
            "expected": [(0, 8)],
        },
        # Multiple empty intervals mixed with non-empty intervals
        {
            "input": [(0, 0), (5, 5), (1, 3), (10, 10), (4, 7), (2, 2)],
            "expected": [(1, 3), (4, 7)],
        },
        # Empty intervals at endpoints of non-empty intervals
        {
            "input": [(3, 3), (3, 6), (6, 6)],
            "expected": [(3, 6)],
        },
        # Complex mixed case: unsorted, overlap, touching, duplicates, empty intervals
        {
            "input": [(12, 16), (1, 4), (0, 0), (3, 7), (10, 12), (7, 9), (5, 5), (15, 20), (1, 4)],
            "expected": [(1, 9), (10, 20)],
        },
        # Input intervals provided as lists
        {
            "input": [[1, 3], [3, 6], [2, 4]],
            "expected": [(1, 6)],
        },
        # Multi-cluster with overlaps and touchings
        {
            "input": [(100, 105), (10, 20), (105, 110), (15, 25), (0, 5), (25, 30)],
            "expected": [(0, 5), (10, 30), (100, 110)],
        },
        # Large integer coordinates
        {
            "input": [(10 ** 18, 10 ** 18 + 10), (10 ** 18 + 10, 10 ** 18 + 20)],
            "expected": [(10 ** 18, 10 ** 18 + 20)],
        },
        # Multiple all-empty intervals
        {
            "input": [(0, 0), (1, 1), (2, 2)],
            "expected": [],
        },
        # Origin interval touching non-empty
        {
            "input": [(0, 0), (0, 1), (1, 2)],
            "expected": [(0, 2)],
        },
    ],
}
