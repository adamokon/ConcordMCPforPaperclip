"""Validation and canonical union of nonnegative integer half-open intervals.

merge_intervals accepts an outer list or tuple (including subclasses), with
list/tuple elements accepted by validate_interval. Other outer types raise
TypeError, including None, generators, iterators, sets, mappings, and strings.
Inputs are never sorted or modified in place. The result is always a new list
of tuples, with empty intervals discarded and overlapping or touching intervals
merged. Every element is validated before empty intervals are discarded.
"""


def validate_interval(pair):
    """Return (start, end) for a valid list or tuple of endpoints.

    Endpoints must be nonnegative integers (excluding bool), with start <= end.
    Invalid containers or endpoint types raise TypeError. Invalid lengths,
    negative endpoints, and reversed ranges raise ValueError. Empty intervals
    are valid here; their treatment during merging is a separate policy.
    """
    if not isinstance(pair, (list, tuple)):
        raise TypeError("interval must be a list or tuple")
    if len(pair) != 2:
        raise ValueError("interval must contain exactly two endpoints")
    start, end = pair
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in (start, end)):
        raise TypeError("interval endpoints must be integers excluding bool")
    if start < 0 or end < 0:
        raise ValueError("interval endpoints must be nonnegative")
    if start > end:
        raise ValueError("interval start must not exceed end")
    return (start, end)


def merge_intervals(intervals):
    """Return the sorted canonical union as a fresh list of endpoint tuples.

    The outer argument must be a list or tuple, including subclasses; all other
    types raise TypeError. Element errors follow validate_interval. Validation
    proceeds in input order and raises on the first invalid element, even when
    earlier elements are empty. No input container is mutated, on success or
    failure. Results have start < end and consecutive end_i < start_(i+1).
    """
    if not isinstance(intervals, (list, tuple)):
        raise TypeError("intervals must be a list or tuple")
    validated = [validate_interval(pair) for pair in intervals]
    ordered = sorted((start, end) for start, end in validated if start < end)
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
