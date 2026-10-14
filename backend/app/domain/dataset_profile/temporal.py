"""Recognize explicit textual date formats without converting cell types."""
from datetime import date, datetime, time
from decimal import Decimal
import re

DATE_TEXT = re.compile(r'([0-9]{4})([-/])([0-9]{2})\2([0-9]{2})(?: ([0-9]{2}):([0-9]{2}):([0-9]{2}))?')
AMBIGUOUS = re.compile(r'([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})(?: ([0-9]{2}):([0-9]{2}):([0-9]{2}))?')
DURATION = re.compile(r'(?:(-?[0-9]+) days?, )?([0-9]+):([0-9]{2}):([0-9]{2}(?:\.[0-9]+)?)')


def candidate_kind(value):
    match = DATE_TEXT.fullmatch(value)
    if match:
        year, _, month, day, hour, minute, second = match.groups()
        try:
            date(int(year), int(month), int(day))
            if hour is not None:
                time(int(hour), int(minute), int(second))
        except ValueError:
            return 'time_invalid'
        return 'time_candidate'
    match = AMBIGUOUS.fullmatch(value)
    if match:
        first, second, year, hour, minute, second_of_minute = match.groups()
        try:
            if hour is not None:
                time(int(hour), int(minute), int(second_of_minute))
        except ValueError:
            return 'time_invalid'
        for month, day in ((first, second), (second, first)):
            try:
                date(int(year), int(month), int(day))
            except ValueError:
                continue
            # Preserve the existing non-YYYY classification even if only one
            # interpretation is valid; this is not a supported conversion format.
            return 'time_ambiguous'
        return 'time_invalid'
    return None


def temporal_key(kind, value):
    if kind == 'date':
        return date.fromisoformat(value)
    if kind == 'datetime':
        return datetime.fromisoformat(value)
    if kind == 'time':
        return time.fromisoformat(value)
    match = DURATION.fullmatch(value)
    if not match:
        raise ValueError('Invalid persisted duration')
    days, hours, minutes, seconds = match.groups()
    return Decimal(days or 0) * 86400 + Decimal(hours) * 3600 + Decimal(minutes) * 60 + Decimal(seconds)
