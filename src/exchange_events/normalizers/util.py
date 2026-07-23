"""Parsing helpers shared by normalizers (design doc §5.2, P5).

Small, pure functions. Raise :class:`NormalizationError` on bad input so the
``BaseNormalizer`` loop can capture the failure and continue with other records.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from ..domain.enums import SessionType
from ..domain.errors import NormalizationError

_UTC = datetime.UTC


def parse_date(value: object, formats: tuple[str, ...] = ()) -> datetime.date:
    """Parse a date, trying ISO-8601 first then any supplied ``strptime`` formats."""
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    s = str(value).strip()
    if not s:
        raise NormalizationError(f"empty date value: {value!r}")
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        pass
    for fmt in formats:
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise NormalizationError(f"unparseable date {s!r} (tried ISO + {formats})")


_MAGNITUDE_SUFFIXES = {"K": 1e3, "M": 1e6, "B": 1e9}


def parse_float(value: object) -> float | None:
    """Parse a float, tolerating ``None``, blanks, placeholders, commas, % and
    magnitude suffixes (``170K`` -> 170000.0, as MarketWatch displays NFP)."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    s = str(value).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "--", "n/a", "N/A", "NA"):
        return None
    suffix = s[-1:].upper()
    multiplier = _MAGNITUDE_SUFFIXES.get(suffix)
    if multiplier is not None:
        s = s[:-1]
    try:
        result = float(s)
    except ValueError as exc:
        raise NormalizationError(f"unparseable number: {value!r}") from exc
    return result * multiplier if multiplier is not None else result


_TIME_FORMATS = ("%H:%M", "%I:%M%p", "%I:%M %p", "%I%p")


def local_time_to_utc(
    day: datetime.date, local_time: str | None, iana_zone: str
) -> datetime.datetime | None:
    """Combine a date + local clock time in ``iana_zone`` into a UTC datetime.

    Accepts 24-hour ``HH:MM`` as well as 12-hour forms like ``8:30am`` (the style
    MarketWatch's calendar page uses). Returns ``None`` when no time is given.
    Enforces P5 (all timestamps UTC).
    """
    if not local_time:
        return None
    s = str(local_time).strip().upper()
    for fmt in _TIME_FORMATS:
        try:
            parsed = datetime.datetime.strptime(s, fmt).time()
            break
        except ValueError:
            continue
    else:
        raise NormalizationError(f"unparseable time: {local_time!r}")
    local = datetime.datetime.combine(day, parsed, tzinfo=ZoneInfo(iana_zone))
    return local.astimezone(_UTC)


# Standard scheduled release times (US/Eastern), one per required release code.
# Sourced from each agency's own published schedule, not guessed:
#   NFP/CPI/PPI — BLS releases at 8:30am ET (bls.gov/news.release, e.g. the JOLTS
#     release PDF header "For release 10:00 a.m. (ET)" confirms the BLS pattern).
#   PCE         — BEA's own embargo notice ("EMBARGOED UNTIL RELEASE AT 8:30 a.m.
#     EDT", bea.gov/sites/default/files/.../pi*.pdf).
#   JOLTS       — BLS, 10:00am ET (bls.gov/news.release/pdf/jolts.pdf).
#   ISM_PMI     — ISM's own release-date page, 10:00am ET (ismworld.org).
#   FOMC        — Federal Reserve statement at 2:00pm ET (federalreserve.gov
#     press releases; press conference follows at 2:30pm).
# FRED/BLS/BEA's own APIs return only a date, no intraday time — this is what
# lets economic releases carry a real `timestamp_utc` despite that (§ P5).
STANDARD_RELEASE_TIMES_ET: dict[str, str] = {
    "NFP": "08:30",
    "CPI": "08:30",
    "PPI": "08:30",
    "PCE": "08:30",
    "JOLTS": "10:00",
    "ISM_PMI": "10:00",
    "FOMC": "14:00",
}


def require(record: dict[str, object], key: str) -> object:
    """Fetch a required key or raise a NormalizationError naming it."""
    if key not in record or record[key] in (None, ""):
        raise NormalizationError(f"missing required field {key!r}", raw_record=record)
    return record[key]


def first(record: dict[str, object], keys: tuple[str, ...], label: str) -> object:
    """Return the first present, non-empty value among ``keys`` or raise."""
    for k in keys:
        if record.get(k) not in (None, ""):
            return record[k]
    raise NormalizationError(f"missing {label} (any of {keys})", raw_record=record)


_SESSION_MAP = {
    "closed": SessionType.FULL_CLOSE,
    "close": SessionType.FULL_CLOSE,
    "full": SessionType.FULL_CLOSE,
    "full_close": SessionType.FULL_CLOSE,
    "holiday": SessionType.FULL_CLOSE,
    "early_close": SessionType.HALF_DAY,
    "early": SessionType.HALF_DAY,
    "half": SessionType.HALF_DAY,
    "half_day": SessionType.HALF_DAY,
    "partial": SessionType.HALF_DAY,
    "special": SessionType.SPECIAL_SESSION,
    "special_session": SessionType.SPECIAL_SESSION,
    "muhurat": SessionType.SPECIAL_SESSION,
}


def to_session_type(
    value: object, default: SessionType = SessionType.FULL_CLOSE
) -> SessionType:
    if value is None:
        return default
    return _SESSION_MAP.get(str(value).strip().lower(), default)
