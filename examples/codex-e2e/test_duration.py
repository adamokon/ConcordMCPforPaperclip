import unittest

from duration import format_duration


class FormatDurationTests(unittest.TestCase):
    def test_boundaries(self):
        cases = (
            (0, "00:00:00"),
            (59, "00:00:59"),
            (60, "00:01:00"),
            (3599, "00:59:59"),
            (3600, "01:00:00"),
            (3661, "01:01:01"),
            (86400, "24:00:00"),
            (360000, "100:00:00"),
        )
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(format_duration(seconds), expected)

    def test_negative_integer(self):
        with self.assertRaises(ValueError):
            format_duration(-1)

    def test_invalid_types(self):
        for value in (1.5, "60", None, True, False):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    format_duration(value)


if __name__ == "__main__":
    unittest.main()
