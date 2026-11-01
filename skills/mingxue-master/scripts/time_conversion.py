"""Offline IANA clock resolution and an explicit approximate solar-clock option.

The input basis describes the clock actually supplied, not a geographic guess.
All returned real instants are UTC; calendar-term comparisons use fixed UTC+08.
"""
from datetime import datetime, timedelta, timezone
import calendar
import json
import math
from pathlib import Path, PurePosixPath
import re
from zoneinfo import ZoneInfo

from resources import get_resources, ResourceError

UTC = timezone.utc
CHINA = timezone(timedelta(hours=8))
TIME_BASES = ("local-clock", "standard-time", "true-solar-time")
DEFAULT_TIMEZONE = "Asia/Shanghai"
SOLAR_FORMULA = ("gamma=2*pi/(365 or 366)*(UTC_day_of_year-1+(UTC_hour-12)/24); "
    "E_minutes=229.18*(0.000075+0.001868*cos(gamma)-0.032077*sin(gamma)"
    "-0.014615*cos(2*gamma)-0.040849*sin(2*gamma)); "
    "apparent_solar_clock=UTC_naive+4*east_longitude_minutes+E_minutes")
SOLAR_MODEL = {
    "method": "annual Fourier approximation of equation of time",
    "formula": SOLAR_FORMULA,
    "longitude_sign": "east positive, west negative, degrees",
    "reference": "https://gml.noaa.gov/grad/solcalc/solareqns.PDF",
    "accuracy": ("Approximate equation of time, not a second-accurate solar ephemeris. "
        "No guaranteed error bound is claimed; longitude measurement error adds 4 minutes per degree. "
        "A 120-second boundary proximity alert is a review threshold, not a certified error bound."),
    "boundary_review_threshold_seconds": 120,
}


def timezone_metadata(resource_root=None):
    root = Path(resource_root) if resource_root is not None else get_resources()
    path = root / "references/timezones/metadata.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResourceError("Offline timezone metadata is missing or invalid") from exc


def load_zone(name, resource_root=None):
    """Read only bundled TZif data, never host/installed-package timezone data."""
    if (not isinstance(name, str) or not name or len(name) > 100 or "\\" in name
            or any(ord(c) < 32 for c in name)):
        raise ValueError("timezone must be a valid bundled IANA zone key")
    parts = name.split("/")
    if (any(p in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9_.+-]+", p, re.ASCII) for p in parts)
            or PurePosixPath(name).is_absolute()):
        raise ValueError("timezone must be a valid bundled IANA zone key")
    root = Path(resource_root) if resource_root is not None else get_resources()
    path = root.joinpath("references", "timezones", *parts)
    try:
        with path.open("rb") as stream:
            if stream.read(4) != b"TZif":
                raise ValueError("timezone is not a bundled IANA zone key")
            stream.seek(0)
            return ZoneInfo.from_file(stream, key=name)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Unknown or invalid IANA timezone: {name!r}") from exc


def validate_options(timezone_name, time_basis, longitude, true_solar, fold):
    if time_basis not in TIME_BASES:
        raise ValueError(f"time_basis must be one of {TIME_BASES}")
    if type(true_solar) is not bool:
        raise ValueError("true_solar must be a boolean")
    if fold is not None and (type(fold) is not int or fold not in (0, 1)):
        raise ValueError("fold must be 0 or 1, or omitted to retain both repeated instants")
    if longitude is not None:
        if isinstance(longitude, bool) or not isinstance(longitude, (int, float)) or not math.isfinite(longitude):
            raise ValueError("longitude must be a finite number, east positive")
        if not -180 <= longitude <= 180:
            raise ValueError("longitude must be -180..180 degrees, east positive")
    if (true_solar or time_basis == "true-solar-time") and longitude is None:
        raise ValueError("true solar time requires explicit --longitude; it is never inferred from timezone")
    if time_basis == "true-solar-time" and fold is not None:
        raise ValueError("--fold resolves repeated civil/standard clocks, not an already-solar input")
    if timezone_name is not None and not isinstance(timezone_name, str):
        raise ValueError("timezone must be an IANA zone key")


def equation_of_time(instant):
    utc = instant.astimezone(UTC)
    hour = utc.hour + utc.minute / 60 + (utc.second + utc.microsecond / 1_000_000) / 3600
    gamma = 2 * math.pi / (366 if calendar.isleap(utc.year) else 365) * (
        utc.timetuple().tm_yday - 1 + (hour - 12) / 24)
    return 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                     - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))


def solar_clock(instant, longitude):
    return instant.astimezone(UTC).replace(tzinfo=None) + timedelta(
        minutes=4 * longitude + equation_of_time(instant))


def solar_to_utc(clock, longitude):
    """Invert the same smooth approximation; never reapply a supplied correction."""
    guess = (clock - timedelta(minutes=4 * longitude)).replace(tzinfo=UTC)
    for _ in range(10):
        new = (clock - timedelta(minutes=4 * longitude + equation_of_time(guess))).replace(tzinfo=UTC)
        if abs((new - guess).total_seconds()) < 0.000002:
            return new
        guess = new
    return guess


def _offset(instant, zone, basis):
    local = instant.astimezone(zone)
    offset = local.utcoffset()
    return offset - (local.dst() or timedelta()) if basis == "standard-time" else offset


def supplied_clock(instant, zone, basis, longitude=None):
    if basis == "true-solar-time":
        clock = solar_clock(instant, longitude)
        # Inversion is rounded to Python microseconds; preserve exact input edges.
        if clock.microsecond <= 5:
            return clock.replace(microsecond=0)
        if clock.microsecond >= 999995:
            return (clock + timedelta(seconds=1)).replace(microsecond=0)
        return clock
    return instant.astimezone(UTC).replace(tzinfo=None) + _offset(instant, zone, basis)


def chart_clock(instant, zone, basis, longitude=None, true_solar=False):
    return (supplied_clock(instant, zone, basis, longitude) if basis == "true-solar-time" else
            solar_clock(instant, longitude) if true_solar
            else supplied_clock(instant, zone, basis, longitude))


def _offset_segments(start, end, zone, basis):
    """Partition at real offset changes. Hourly probes also cover historical offsets.

    TZif offset changes in the bundled data are separated by more than one hour.
    Binary search retains second-resolution transition boundaries.
    """
    cursor, segment_start = start, start
    previous = _offset(start, zone, basis)
    segments = []
    while cursor < end:
        stop = min(cursor + timedelta(hours=1), end)
        current = _offset(stop, zone, basis)
        if current != previous:
            left, right = cursor, stop
            while (right - left).total_seconds() > 1:
                middle = left + timedelta(seconds=int((right - left).total_seconds()) // 2)
                if _offset(middle, zone, basis) == previous:
                    left = middle
                else:
                    right = middle
            transition = right
            segments.append((segment_start, transition, previous))
            segment_start = transition
            previous = current
        cursor = stop
    segments.append((segment_start, end, previous))
    return segments


def select_fold_ranges(ranges, zone, basis, fold):
    """Choose repeated clock cells while preserving every unique clock cell.

    Input ranges have a constant effective offset. A historical rollback may
    begin partway through a supplied minute, so range starts alone cannot tell
    which portion repeats. Partition their complete local-clock intersections.
    """
    mapped, edges = [], set()
    for a, b in ranges:
        offset = _offset(a, zone, basis)
        local_start = a.replace(tzinfo=None) + offset
        local_end = b.replace(tzinfo=None) + offset
        mapped.append((local_start, local_end, offset))
        edges.update((local_start, local_end))
    repeated = False
    chosen = []
    ordered = sorted(edges)
    for left, right in zip(ordered, ordered[1:]):
        matches = sorted(((left - offset).replace(tzinfo=UTC),
                          (right - offset).replace(tzinfo=UTC), offset)
                         for local_start, local_end, offset in mapped
                         if local_start <= left and right <= local_end)
        if not matches:
            continue
        if len(matches) > 1:
            repeated = True
        # fold applies only to repeated cells. A sole match survives either
        # choice; dropping it would invent a hole in the supplied minute.
        chosen.append(matches[0] if len(matches) == 1 or fold == 0 else matches[-1])
    if fold == 1 and not repeated:
        raise ValueError("fold=1 is only valid for a repeated clock time")
    merged = []
    for a, b, offset in sorted(chosen):
        if merged and merged[-1][1] == a and merged[-1][2] == offset:
            merged[-1] = (merged[-1][0], b, offset)
        else:
            merged.append((a, b, offset))
    return [(a, b) for a, b, _ in merged]


def resolve_range(start, end, zone, basis, longitude=None, fold=None):
    """Return disjoint [UTC start, UTC end) intervals, keeping repeated instants."""
    if basis == "true-solar-time":
        return [(solar_to_utc(start, longitude), solar_to_utc(end, longitude))]
    lower = (start - timedelta(hours=26)).replace(tzinfo=UTC)
    upper = (end + timedelta(hours=26)).replace(tzinfo=UTC)
    result = []
    for a, b, offset in _offset_segments(lower, upper, zone, basis):
        left = max(a, (start - offset).replace(tzinfo=UTC))
        right = min(b, (end - offset).replace(tzinfo=UTC))
        if left < right:
            result.append((left, right))
    result.sort()
    if fold is not None:
        result = select_fold_ranges(result, zone, basis, fold)
    if not result:
        raise ValueError("The supplied clock time does not exist in this IANA timezone (clock-forward gap)")
    return result


def clock_record(instant, zone, basis, longitude=None, true_solar=False):
    local = instant.astimezone(zone)
    utc = instant.astimezone(UTC)
    standard_offset = local.utcoffset() - (local.dst() or timedelta())
    adopted = chart_clock(utc, zone, basis, longitude, true_solar)
    raw = supplied_clock(utc, zone, basis, longitude)
    solar = true_solar or basis == "true-solar-time"
    changes = []
    if basis == "local-clock":
        changes.append({"step": "resolve_civil_clock", "offset_seconds": local.utcoffset().total_seconds(),
                        "dst_seconds": (local.dst() or timedelta()).total_seconds(), "fold": local.fold})
    elif basis == "standard-time":
        changes.append({"step": "resolve_already_standard_clock", "standard_offset_seconds": standard_offset.total_seconds(),
                        "note": "DST is not subtracted from the supplied clock a second time"})
    else:
        changes.append({"step": "invert_already_solar_clock", "note": "supplied solar correction is not applied twice"})
    changes.append({"step": "utc_to_library", "fixed_offset_seconds": 28800})
    if solar:
        changes.append({"step": "derive_or_preserve_solar_chart_clock", "east_longitude_degrees": longitude,
            "longitude_minutes_from_utc": 4 * longitude, "equation_of_time_minutes": equation_of_time(utc),
            "correction_from_supplied_seconds": (adopted - raw).total_seconds()})
    return {
        "original_clock": raw.isoformat(sep=" "), "input_time_basis": basis,
        "utc": utc.isoformat(), "local_civil_clock": local.isoformat(sep=" "),
        "standard_clock": (utc.replace(tzinfo=None) + standard_offset).isoformat(sep=" "),
        "utc_offset_seconds": local.utcoffset().total_seconds(),
        "standard_offset_seconds": standard_offset.total_seconds(),
        "dst_seconds": (local.dst() or timedelta()).total_seconds(), "fold": local.fold,
        "library_clock": utc.astimezone(CHINA).isoformat(sep=" "),
        "chart_clock": adopted.isoformat(sep=" "),
        "chart_time_basis": "true-solar-time" if solar else basis,
        "correction_steps": changes,
    }


def near_solar_boundary(instant, zone, basis, longitude, true_solar, sect):
    if not (true_solar or basis == "true-solar-time"):
        return False
    selected = chart_clock(instant, zone, basis, longitude, true_solar)
    seconds = selected.hour * 3600 + selected.minute * 60 + selected.second + selected.microsecond / 1e6
    edges = [0, 86400, *(hour * 3600 for hour in range(1, 24, 2))]
    return min(abs(seconds - edge) for edge in edges) <= 120
