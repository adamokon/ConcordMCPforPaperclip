def format_duration(seconds):
    """Format nonnegative integer seconds as HH:MM:SS without wrapping hours."""
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise TypeError("seconds must be an integer")
    if seconds < 0:
        raise ValueError("seconds must be nonnegative")
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
