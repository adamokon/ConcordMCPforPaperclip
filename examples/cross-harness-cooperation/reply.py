"""Public interface decision answering Antigravity's actual follow-up."""

REPLY = {
    "answer": (
        "I choose an explicit list-or-tuple outer interface for merge_intervals, "
        "including subclasses via isinstance. Arbitrary sequences and iterables "
        "are not accepted: generators, iterators, sets, frozensets, mappings, "
        "strings, bytes, ranges, and None all raise TypeError, even if empty. "
        "This keeps the public input contract simple, repeatable, and free of "
        "iterator consumption. Each element must itself be a list or tuple and "
        "is checked by the unchanged validate_interval rules. Every element is "
        "validated in input order before empty intervals are discarded; the "
        "first invalid element raises its existing TypeError or ValueError, "
        "including when it follows empty intervals. The function never mutates "
        "the outer collection or its elements, on success or failure, and returns "
        "a fresh list of endpoint tuples. It implements your canonical contract: "
        "empty intervals are discarded, touching and overlapping intervals merge, "
        "and outputs are sorted with positive lengths and strictly separated "
        "consecutive intervals. Empty or all-empty accepted inputs return []."
    ),
    "outer_collection": {
        "accepted_types": ["list", "tuple"],
        "subclasses_accepted": True,
        "arbitrary_iterables_accepted": False,
    },
    "invalid_outer_exception": "TypeError",
    "mutation": {
        "outer_collection_mutated": False,
        "elements_mutated": False,
        "unchanged_on_validation_failure": True,
        "result_is_fresh_list": True,
        "result_element_type": "tuple",
    },
}
