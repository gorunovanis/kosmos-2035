"""Model calendar of the case: 365-day years without 29 February (TEAM_ASSUMPTION A1).

Dates are strings "YYYY-MM-DD". Day index 0 = 1 January of EPOCH_YEAR (the preparatory
year before the planning horizon). Lead times are converted to whole days:
week = 7 days, month = ceil(n * 365 / 12) days, year = 365 days.
"""
from __future__ import annotations

import math

EPOCH_YEAR = 2034
DAYS_IN_YEAR = 365
MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_CUM = [0]
for _m in MONTH_DAYS:
    _CUM.append(_CUM[-1] + _m)


class DateError(ValueError):
    pass


def parse_date(s: str) -> tuple[int, int, int]:
    if not isinstance(s, str) or len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise DateError(f"bad date format {s!r}, expected YYYY-MM-DD")
    try:
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    except ValueError as exc:
        raise DateError(f"bad date {s!r}") from exc
    if not 1 <= m <= 12:
        raise DateError(f"bad month in {s!r}")
    if not 1 <= d <= MONTH_DAYS[m - 1]:
        raise DateError(f"bad day in {s!r} (model calendar has no 29 February)")
    return y, m, d


def to_index(s: str) -> int:
    y, m, d = parse_date(s)
    return (y - EPOCH_YEAR) * DAYS_IN_YEAR + _CUM[m - 1] + (d - 1)


def to_date(i: int) -> str:
    y, rem = divmod(int(i), DAYS_IN_YEAR)
    y += EPOCH_YEAR
    m = 1
    while rem >= _CUM[m]:
        m += 1
    d = rem - _CUM[m - 1] + 1
    return f"{y:04d}-{m:02d}-{d:02d}"


def year_of(i: int) -> int:
    return EPOCH_YEAR + int(i) // DAYS_IN_YEAR


def year_start(year: int) -> int:
    return (year - EPOCH_YEAR) * DAYS_IN_YEAR


def year_end(year: int) -> int:
    """Index of 31 December of the year (inclusive)."""
    return year_start(year) + DAYS_IN_YEAR - 1


def lead_days(value: float, unit: str) -> int:
    unit = (unit or "").strip().lower()
    if unit == "day":
        return int(math.ceil(value))
    if unit == "week":
        return int(math.ceil(value * 7))
    if unit == "month":
        return int(math.ceil(value * DAYS_IN_YEAR / 12 - 1e-9))
    if unit == "year":
        return int(math.ceil(value * DAYS_IN_YEAR))
    raise DateError(f"unknown lead time unit {unit!r}")


def overlap_days(a0: int, a1: int, b0: int, b1: int) -> int:
    """Number of days in the intersection of inclusive index ranges."""
    lo, hi = max(a0, b0), min(a1, b1)
    return max(0, hi - lo + 1)
