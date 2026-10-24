"""Supervisor checks independent of the worker's own test assertions."""

from duration import format_duration


def main():
    for value in range(400001):
        result = format_duration(value)
        parts = result.split(":")
        assert len(parts) == 3
        hours, minutes, seconds = map(int, parts)
        assert hours * 3600 + minutes * 60 + seconds == value
        assert hours >= 0 and 0 <= minutes < 60 and 0 <= seconds < 60
        assert len(parts[0]) >= 2 and len(parts[1]) == len(parts[2]) == 2
        assert result.isascii()
    assert format_duration(10**30) == "277777777777777777777777777:46:40"
    print("PASS: 400001 roundtrip cases and huge integer")


if __name__ == "__main__":
    main()
