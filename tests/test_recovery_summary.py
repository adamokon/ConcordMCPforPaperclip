"""Unit tests for Concord recovery summary function."""

import copy
import unittest

from concord_paperclip.recovery_summary import summarize_recovery


class TestSummarizeRecoveryEmpty(unittest.TestCase):
    """Tests for empty event collections."""

    def test_empty_events_list(self):
        result = summarize_recovery([])
        expected = {
            "tasks": 0,
            "events": 0,
            "retries": 0,
            "resumed": 0,
            "blocked": 0,
            "waiting": 0,
            "received": 0,
        }
        self.assertEqual(result, expected)


class TestSummarizeRecoveryValid(unittest.TestCase):
    """Tests for valid event inputs and history combinations."""

    def test_single_events_all_actions(self):
        actions_to_field = {
            "retry": "retries",
            "bind": "resumed",
            "wait": "waiting",
            "block": "blocked",
            "receive": "received",
        }
        for action, field in actions_to_field.items():
            with self.subTest(action=action):
                event = {
                    "task_id": "12345678-abcd-4000-8000-123456789abc",
                    "action": action,
                }
                result = summarize_recovery([event])
                expected = {
                    "tasks": 1,
                    "events": 1,
                    "retries": 1 if field == "retries" else 0,
                    "resumed": 1 if field == "resumed" else 0,
                    "blocked": 1 if field == "blocked" else 0,
                    "waiting": 1 if field == "waiting" else 0,
                    "received": 1 if field == "received" else 0,
                }
                self.assertEqual(result, expected)

    def test_single_event_with_code(self):
        event = {
            "task_id": "12345678-abcd-4000-8000-123456789abc",
            "action": "bind",
            "code": "STEP_OK_01",
        }
        result = summarize_recovery([event])
        self.assertEqual(
            result,
            {
                "tasks": 1,
                "events": 1,
                "retries": 0,
                "resumed": 1,
                "blocked": 0,
                "waiting": 0,
                "received": 0,
            },
        )

    def test_valid_mixed_histories_across_tasks(self):
        task_a = "12345678-abcd-4000-8000-123456789abc"
        task_b = "11111111-2222-3333-4444-555555555555"
        task_c = "abcdef01-2345-6789-abcd-ef0123456789"

        events = [
            {"task_id": task_a, "action": "retry", "code": "R1"},
            {"task_id": task_b, "action": "wait"},
            {"task_id": task_a, "action": "bind", "code": "B1"},
            {"task_id": task_c, "action": "block"},
            {"task_id": task_b, "action": "receive", "code": "RCV"},
            {"task_id": task_a, "action": "retry"},
            {"task_id": task_c, "action": "receive"},
        ]
        result = summarize_recovery(events)
        self.assertEqual(
            result,
            {
                "tasks": 3,
                "events": 7,
                "retries": 2,
                "resumed": 1,
                "blocked": 1,
                "waiting": 1,
                "received": 2,
            },
        )

    def test_repeated_identical_events(self):
        event = {
            "task_id": "12345678-abcd-4000-8000-123456789abc",
            "action": "retry",
            "code": "RETRY_ONCE",
        }
        events = [event, event, event]
        result = summarize_recovery(events)
        self.assertEqual(
            result,
            {
                "tasks": 1,
                "events": 3,
                "retries": 3,
                "resumed": 0,
                "blocked": 0,
                "waiting": 0,
                "received": 0,
            },
        )

    def test_multiple_events_same_task(self):
        task = "12345678-abcd-4000-8000-123456789abc"
        events = [
            {"task_id": task, "action": "wait"},
            {"task_id": task, "action": "bind"},
            {"task_id": task, "action": "receive"},
        ]
        result = summarize_recovery(events)
        self.assertEqual(
            result,
            {
                "tasks": 1,
                "events": 3,
                "retries": 0,
                "resumed": 1,
                "blocked": 0,
                "waiting": 1,
                "received": 1,
            },
        )

    def test_limit_1000_events(self):
        task = "12345678-abcd-4000-8000-123456789abc"
        events = [{"task_id": task, "action": "retry"} for _ in range(1000)]
        result = summarize_recovery(events)
        self.assertEqual(
            result,
            {
                "tasks": 1,
                "events": 1000,
                "retries": 1000,
                "resumed": 0,
                "blocked": 0,
                "waiting": 0,
                "received": 0,
            },
        )

    def test_code_edge_cases_valid(self):
        task = "12345678-abcd-4000-8000-123456789abc"
        # Length 0 string
        res_empty = summarize_recovery([{"task_id": task, "action": "retry", "code": ""}])
        self.assertEqual(res_empty["events"], 1)

        # Length 80 string (printable ASCII)
        code_80 = "a" * 80
        res_80 = summarize_recovery([{"task_id": task, "action": "retry", "code": code_80}])
        self.assertEqual(res_80["events"], 1)

        # Printable ASCII symbols and spaces
        code_symbols = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`{|}~"
        res_sym = summarize_recovery([{"task_id": task, "action": "retry", "code": code_symbols}])
        self.assertEqual(res_sym["events"], 1)


class TestSummarizeRecoveryLimits(unittest.TestCase):
    """Tests for event count boundaries."""

    def test_limit_1001_events_rejected(self):
        task = "12345678-abcd-4000-8000-123456789abc"
        events = [{"task_id": task, "action": "retry"} for _ in range(1001)]
        with self.assertRaises(ValueError):
            summarize_recovery(events)


class TestSummarizeRecoveryCollectionAndItemTypes(unittest.TestCase):
    """Tests for invalid collection and item types."""

    def test_collection_wrong_types(self):
        task = "12345678-abcd-4000-8000-123456789abc"
        valid_event = {"task_id": task, "action": "retry"}
        invalid_collections = [
            None,
            123,
            "invalid_collection",
            (valid_event,),
            {"events": valid_event},
            {valid_event["task_id"]},
            (x for x in [valid_event]),
        ]
        for coll in invalid_collections:
            with self.subTest(coll_type=type(coll)):
                with self.assertRaises(ValueError):
                    summarize_recovery(coll)

    def test_item_wrong_types(self):
        invalid_items = [
            None,
            123,
            "string_item",
            ["task_id", "12345678-abcd-4000-8000-123456789abc"],
            ("12345678-abcd-4000-8000-123456789abc", "retry"),
        ]
        for item in invalid_items:
            with self.subTest(item_type=type(item)):
                with self.assertRaises(ValueError):
                    summarize_recovery([item])


class TestSummarizeRecoveryUUIDValidation(unittest.TestCase):
    """Tests for canonical lowercase UUID validation."""

    def test_uppercase_uuid_rejected(self):
        event = {
            "task_id": "12345678-ABCD-4000-8000-123456789ABC",
            "action": "retry",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_mixed_case_uuid_rejected(self):
        event = {
            "task_id": "12345678-abcd-4000-8000-123456789aBc",
            "action": "retry",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_uuid_missing_hyphens_rejected(self):
        event = {
            "task_id": "0bdcd4a2e6314a31baf26322ba4eb177",
            "action": "retry",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_uuid_wrong_hyphen_positions_rejected(self):
        event = {
            "task_id": "0bdcd4a-2e631-4a31-baf2-6322ba4eb177",
            "action": "retry",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_uuid_too_short_rejected(self):
        event = {
            "task_id": "0bdcd4a2-e631-4a31-baf2-6322ba4eb17",
            "action": "retry",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_uuid_too_long_rejected(self):
        event = {
            "task_id": "12345678-abcd-4000-8000-123456789abc7",
            "action": "retry",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_uuid_invalid_characters_rejected(self):
        event = {
            "task_id": "0bdcd4a2-e631-4a31-baf2-6322ba4eb17g",
            "action": "retry",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_uuid_non_string_types_rejected(self):
        invalid_uuids = [12345, None, [], {}, 3.14]
        for val in invalid_uuids:
            with self.subTest(uuid_val=val):
                with self.assertRaises(ValueError):
                    summarize_recovery([{"task_id": val, "action": "retry"}])

    def test_uuid_whitespace_and_newlines_rejected(self):
        invalid_uuids = [
            " 12345678-abcd-4000-8000-123456789abc",
            "12345678-abcd-4000-8000-123456789abc ",
            "12345678-abcd-4000-8000-123456789abc\n",
            "\n12345678-abcd-4000-8000-123456789abc",
            "",
        ]
        for val in invalid_uuids:
            with self.subTest(uuid_val=repr(val)):
                with self.assertRaises(ValueError):
                    summarize_recovery([{"task_id": val, "action": "retry"}])


class TestSummarizeRecoveryActionValidation(unittest.TestCase):
    """Tests for action validation."""

    def test_unknown_actions_rejected(self):
        unknown_actions = [
            "start",
            "stop",
            "resume",
            "retries",
            "binding",
            "WAITING",
            "receive_all",
            "drop",
        ]
        for act in unknown_actions:
            with self.subTest(action=act):
                event = {
                    "task_id": "12345678-abcd-4000-8000-123456789abc",
                    "action": act,
                }
                with self.assertRaises(ValueError):
                    summarize_recovery([event])

    def test_uppercase_actions_rejected(self):
        uppercase_actions = ["RETRY", "BIND", "WAIT", "BLOCK", "RECEIVE"]
        for act in uppercase_actions:
            with self.subTest(action=act):
                event = {
                    "task_id": "12345678-abcd-4000-8000-123456789abc",
                    "action": act,
                }
                with self.assertRaises(ValueError):
                    summarize_recovery([event])

    def test_non_string_actions_rejected(self):
        invalid_actions = [None, 1, True, [], {}]
        for act in invalid_actions:
            with self.subTest(action=repr(act)):
                event = {
                    "task_id": "12345678-abcd-4000-8000-123456789abc",
                    "action": act,
                }
                with self.assertRaises(ValueError):
                    summarize_recovery([event])

    def test_action_with_spaces_or_empty_rejected(self):
        for act in ["", "retry ", " retry", "retry\n"]:
            with self.subTest(action=repr(act)):
                event = {
                    "task_id": "12345678-abcd-4000-8000-123456789abc",
                    "action": act,
                }
                with self.assertRaises(ValueError):
                    summarize_recovery([event])


class TestSummarizeRecoveryKeysValidation(unittest.TestCase):
    """Tests for event dictionary key validation (missing or extra keys)."""

    def test_missing_task_id_rejected(self):
        event = {"action": "retry"}
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_missing_action_rejected(self):
        event = {"task_id": "12345678-abcd-4000-8000-123456789abc"}
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_empty_dict_rejected(self):
        with self.assertRaises(ValueError):
            summarize_recovery([{}])

    def test_extra_key_without_code_rejected(self):
        event = {
            "task_id": "12345678-abcd-4000-8000-123456789abc",
            "action": "retry",
            "extra_key": "unexpected",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_extra_key_with_code_rejected(self):
        event = {
            "task_id": "12345678-abcd-4000-8000-123456789abc",
            "action": "retry",
            "code": "C1",
            "extra_key": "unexpected",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_wrong_key_names_rejected(self):
        event = {
            "taskId": "12345678-abcd-4000-8000-123456789abc",
            "action": "retry",
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])


class TestSummarizeRecoveryCodeValidation(unittest.TestCase):
    """Tests for code property validation."""

    def test_non_string_code_rejected(self):
        invalid_codes = [None, 123, 45.67, True, [], {}]
        for code_val in invalid_codes:
            with self.subTest(code=repr(code_val)):
                event = {
                    "task_id": "12345678-abcd-4000-8000-123456789abc",
                    "action": "retry",
                    "code": code_val,
                }
                with self.assertRaises(ValueError):
                    summarize_recovery([event])

    def test_code_exceeds_80_chars_rejected(self):
        event = {
            "task_id": "12345678-abcd-4000-8000-123456789abc",
            "action": "retry",
            "code": "a" * 81,
        }
        with self.assertRaises(ValueError):
            summarize_recovery([event])

    def test_code_non_ascii_rejected(self):
        non_ascii_codes = [
            "error \u00e9",
            "caf\u00e9",
            "\u2014",
            "\u4e16\u754c",
            "\U0001f600",
        ]
        for code_val in non_ascii_codes:
            with self.subTest(code=repr(code_val)):
                event = {
                    "task_id": "12345678-abcd-4000-8000-123456789abc",
                    "action": "retry",
                    "code": code_val,
                }
                with self.assertRaises(ValueError):
                    summarize_recovery([event])

    def test_code_control_characters_rejected(self):
        control_chars = [
            "line1\nline2",
            "val\r",
            "col1\tcol2",
            "prefix\x00suffix",
            "bell\x07",
            "esc\x1b",
            "del\x7f",
        ]
        for code_val in control_chars:
            with self.subTest(code=repr(code_val)):
                event = {
                    "task_id": "12345678-abcd-4000-8000-123456789abc",
                    "action": "retry",
                    "code": code_val,
                }
                with self.assertRaises(ValueError):
                    summarize_recovery([event])


class TestSummarizeRecoveryPurityAndSecurity(unittest.TestCase):
    """Tests ensuring no mutation of caller data and no echoing of event bodies in errors."""

    def test_no_mutation_of_caller_data(self):
        task_1 = "12345678-abcd-4000-8000-123456789abc"
        task_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        original_events = [
            {"task_id": task_1, "action": "retry", "code": "C1"},
            {"task_id": task_2, "action": "bind"},
            {"task_id": task_1, "action": "receive", "code": "RCV"},
        ]
        cloned_events = copy.deepcopy(original_events)

        result = summarize_recovery(original_events)
        self.assertIsInstance(result, dict)
        self.assertEqual(original_events, cloned_events)

    def test_no_echo_of_event_bodies_in_errors(self):
        sentinel_uuid = "SENTINEL-UUID-0BDCD4A2-LEAK-TEST"
        sentinel_action = "SENTINEL_ACTION_LEAK_TEST"
        sentinel_code = "SENTINEL_CODE_\x00_LEAK_TEST"
        sentinel_key = "SENTINEL_KEY_LEAK_TEST"

        test_cases = [
            {"task_id": sentinel_uuid, "action": "retry"},
            {"task_id": "12345678-abcd-4000-8000-123456789abc", "action": sentinel_action},
            {
                "task_id": "12345678-abcd-4000-8000-123456789abc",
                "action": "retry",
                "code": sentinel_code,
            },
            {
                "task_id": "12345678-abcd-4000-8000-123456789abc",
                "action": "retry",
                sentinel_key: "val",
            },
        ]

        sentinels = [
            sentinel_uuid,
            sentinel_action,
            sentinel_code,
            sentinel_key,
        ]

        for event in test_cases:
            try:
                summarize_recovery([event])
                self.fail("Expected ValueError was not raised")
            except ValueError as exc:
                err_msg = str(exc)
                for sentinel in sentinels:
                    self.assertNotIn(
                        sentinel,
                        err_msg,
                        f"Error message leaked sentinel payload: {err_msg}",
                    )


if __name__ == "__main__":
    unittest.main()


class TestIndependentSummaryOracle(unittest.TestCase):
    def test_all_short_two_task_histories(self):
        import itertools
        from collections import Counter
        identities = ['12345678-abcd-4000-8000-123456789abc',
                      'aaaaaaaa-bbbb-4000-8000-111111111111']
        actions = ['retry', 'bind', 'wait', 'block', 'receive']
        fields = dict(zip(actions, ['retries', 'resumed', 'waiting', 'blocked', 'received']))
        checked = 0
        for length in range(5):
            for sequence in itertools.product(range(10), repeat=length):
                events = [{'task_id': identities[x // 5], 'action': actions[x % 5]} for x in sequence]
                counts = Counter(e['action'] for e in events)
                expected = {field: counts[action] for action, field in fields.items()}
                expected.update(tasks=len({e['task_id'] for e in events}), events=length)
                self.assertEqual(summarize_recovery(events), expected)
                checked += 1
        self.assertEqual(checked, 11111)
