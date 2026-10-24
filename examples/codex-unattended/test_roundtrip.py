import unittest
from duration import format_duration


class RoundtripAcceptance(unittest.TestCase):
    def test_roundtrip_and_large_integer(self):
        for value in range(400001):
            text = format_duration(value)
            parts = text.split(":")
            self.assertEqual(len(parts), 3)
            hours, minutes, seconds = map(int, parts)
            self.assertEqual(hours * 3600 + minutes * 60 + seconds, value)
            self.assertTrue(0 <= minutes < 60 and 0 <= seconds < 60)
            self.assertGreaterEqual(len(parts[0]), 2)
            self.assertEqual(len(parts[1]), 2)
            self.assertEqual(len(parts[2]), 2)
        self.assertEqual(format_duration(10**30), "277777777777777777777777777:46:40")
