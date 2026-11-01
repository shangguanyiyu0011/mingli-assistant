"""One offline, instant-aware calendar API for every birth-chart entry point."""
import argparse
from datetime import date, datetime, time, timedelta
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
from resources import get_resources, ResourceError
from pillar_details import build_details
from time_conversion import (CHINA, UTC, DEFAULT_TIMEZONE, SOLAR_MODEL, TIME_BASES,
    chart_clock, clock_record, load_zone, near_solar_boundary, resolve_range, select_fold_ranges,
    solar_to_utc, supplied_clock, timezone_metadata, validate_options)

PILLAR_KEYS = ("year", "month", "day", "hour")
GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
JIAZI = frozenset(GAN[i % 10] + ZHI[i % 12] for i in range(60))


def validate_shichen(value, time_value=None):
    if value is not None:
        if not isinstance(value, str) or len(value) != 1 or value not in ZHI:
            raise ValueError("shichen must be one of 子丑寅卯辰巳午未申酉戌亥")
        if time_value is not None:
            raise ValueError("time and shichen cannot both be supplied")
    return value


def is_valid_pillar(value):
    return isinstance(value, str) and value in JIAZI


def validate_pillars(pillars, *, allow_unknown=False):
    if not isinstance(pillars, dict) or set(pillars) != set(PILLAR_KEYS):
        raise ValueError("pillars must contain exactly year, month, day, hour")
    for key in PILLAR_KEYS:
        if pillars[key] is None and allow_unknown:
            continue
        if not is_valid_pillar(pillars[key]):
            raise ValueError(f"Invalid sixty-cycle pillar {key}: {pillars[key]!r}")
    return pillars


def calendar_library(resource_root=None):
    root = resource_root if resource_root is not None else get_resources()
    vendor = root / "references/upstream/tongren-mingdian-skillpack/scripts/_vendor"
    if not (vendor / "lunar_python/__init__.py").is_file():
        raise ResourceError("Verified resources do not contain the bundled lunar_python library")
    # Do not create bytecode/user files in either the source override or cache.
    sys.dont_write_bytecode = True
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    module = importlib.import_module("lunar_python")
    if not Path(module.__file__).resolve().is_relative_to(vendor.resolve()):
        raise ResourceError("A different lunar_python is already imported; run in a fresh Python process")
    return module


def _parse_input(date_value, time_value, calendar, leap, sect, timezone, time_basis, gender, yun_sect):
    if not isinstance(date_value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value, re.ASCII):
        raise ValueError("date must be exactly YYYY-MM-DD")
    y, m, d = map(int, date_value.split("-"))
    if not 1 <= y <= 9998 or not 1 <= m <= 12:
        raise ValueError("input year must be 1583..9998 and month 01..12")
    if y < 1583:
        raise ValueError("Real-time conversion requires input year 1583..9998: the calendar library's earlier Julian/Gregorian convention is incompatible with the Gregorian datetime/IANA clock model. Use explicit three/four-pillar lookup for older records.")
    if calendar not in ("solar", "lunar") or type(leap) is not bool:
        raise ValueError("calendar must be solar/lunar; leap must be a boolean")
    if leap and calendar != "lunar":
        raise ValueError("--leap requires --calendar lunar")
    if calendar == "solar":
        date(y, m, d)
    elif not 1 <= d <= 30:
        raise ValueError("lunar day must be 01..30; actual month length is checked separately")
    if type(sect) is not int or sect not in (1, 2):
        raise ValueError("sect must be 1 (23:00 day change) or 2 (00:00 day change)")
    if type(yun_sect) is not int or yun_sect not in (1, 2):
        raise ValueError("yun_sect must be 1 or 2")
    if gender not in (None, "male", "female"):
        raise ValueError("gender must be male/female under the traditional binary calculation rule")
    if time_basis not in TIME_BASES:
        raise ValueError(f"time_basis must be one of {TIME_BASES}")
    if timezone is not None and (not isinstance(timezone, str) or not timezone.strip()
            or len(timezone) > 100 or any(ord(c) < 32 for c in timezone)):
        raise ValueError("timezone must be a nonempty label of at most 100 characters")
    clock = None
    if time_value is not None:
        if not isinstance(time_value, str) or not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", time_value, re.ASCII):
            raise ValueError("time must be HH:MM or HH:MM:SS, without offsets or fractions")
        clock = time.fromisoformat(time_value)
    return y, m, d, clock


def _ec(lunar, sect):
    ec = lunar.getEightChar()
    ec.setSect(sect)
    return ec


def _pillars(ec):
    return dict(zip(PILLAR_KEYS, (ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime())))


def _yun(ec, gender, method):
    yun = ec.getYun(1 if gender == "male" else 0, method)
    return {
        "status": "calculated", "method": f"bundled lunar_python EightChar.getYun, sect={method}",
        "method_detail": ("traditional branch-hour difference: 3 days = 1 year" if method == 1
                          else "minute difference: 4320 minutes = 1 year, 360 = 1 month, 12 = 1 day"),
        "gender_rule": "male/female input; yang-year male or yin-year female forward, otherwise backward",
        "direction": "forward" if yun.isForward() else "backward",
        "start_offset": {"years": yun.getStartYear(), "months": yun.getStartMonth(),
                         "days": yun.getStartDay(), "hours": yun.getStartHour()},
        "start_solar": yun.getStartSolar().toYmdHms(),
        "age_basis": "nominal ages supplied by the bundled library; index 0 is pre-start period",
        "dayun": [{"index": dy.getIndex(), "pillar": dy.getGanZhi(),
                   "start_year": dy.getStartYear(), "end_year": dy.getEndYear(),
                   "start_age": dy.getStartAge(), "end_age": dy.getEndAge()}
                  for dy in yun.getDaYun(9) if dy.getIndex() > 0],
    }


def _lunar_at(lib, clock):
    return lib.Solar.fromYmdHms(clock.year, clock.month, clock.day,
                               clock.hour, clock.minute, clock.second).getLunar()


def _instant_pillars(lib, instant, selected_clock, sect):
    # The library's JieQi table is fixed China UTC+08. Never compare a local or
    # solar wall-clock directly against those terms.
    real_lunar = _lunar_at(lib, instant.astimezone(CHINA))
    real_ec = _ec(real_lunar, sect)
    day_ec = _ec(_lunar_at(lib, selected_clock), sect)
    return {"year": real_ec.getYear(), "month": real_ec.getMonth(),
            "day": day_ec.getDay(), "hour": day_ec.getTime()}, real_lunar


def _lunar_day(lib, y, m, d, leap):
    signed_month = -m if leap else m
    month = lib.LunarYear.fromYear(y).getMonth(signed_month)
    if month is None or month.getYear() != y:
        raise ValueError(f"Lunar year {y} has no {'leap ' if leap else ''}month {m}")
    if d > month.getDayCount():
        raise ValueError(f"Lunar month has only {month.getDayCount()} days")
    return date.fromisoformat(lib.Lunar.fromYmd(y, signed_month, d).getSolar().toYmd())


def _birth_ranges(lib, y, m, d, clock, calendar, leap, zone, basis, longitude, fold, precision, shichen=None):
    """Lunar date is a China UTC+08 calendar date, even for overseas clocks."""
    duration = timedelta(days=1) if clock is None else timedelta(minutes=1) if precision == "minute" else timedelta(microseconds=1)
    china_day = _lunar_day(lib, y, m, d, leap) if calendar == "lunar" else None
    if calendar == "lunar" and clock is None and shichen is None:
        start = datetime.combine(china_day, time(), CHINA).astimezone(UTC)
        # Segment by zone offset so fold possibilities remain separate.
        return [(start, start + timedelta(days=1))], china_day
    raw_day = china_day if calendar == "lunar" else date(y, m, d)
    dates = [raw_day + timedelta(days=n) for n in range(-2, 3)] if china_day else [raw_day]
    china_start = datetime.combine(china_day, time(), CHINA).astimezone(UTC) if china_day else None
    ranges = []
    for current in dates:
        if shichen is not None:
            index = ZHI.index(shichen)
            # A civil date + 子 does not identify early or late Zi.
            hours = [(0, 1), (23, 24)] if index == 0 else [(index * 2 - 1, index * 2 + 1)]
            midnight = datetime.combine(current, time())
            intervals = [(midnight + timedelta(hours=a), midnight + timedelta(hours=b)) for a, b in hours]
        else:
            start = datetime.combine(current, clock or time())
            intervals = [(start, start + duration)]
        for start, end in intervals:
            try:
                resolved = resolve_range(start, end, zone, basis, longitude,
                                         fold if china_day is None and shichen is None else None)
            except ValueError:
                if china_day is None and shichen is None:
                    raise
                continue
            for a, b in resolved:
                if china_day:
                    a, b = max(a, china_start), min(b, china_start + timedelta(days=1))
                if a < b:
                    ranges.append((a, b))
    if not ranges:
        raise ValueError("The supplied clock has no real instant within the specified China lunar date; check timezone/fold")
    ranges.sort()
    if (china_day or shichen is not None) and fold is not None:
        ranges = select_fold_ranges(ranges, zone, basis, fold)
    if precision == "second":
        ranges = [(a, a) for a, _ in ranges]
    return ranges, china_day


def _terms_near(lib, ranges):
    terms = {}
    for a, b in ranges:
        for instant in (a, b):
            lunar = _lunar_at(lib, instant.astimezone(CHINA))
            for name, solar in lunar.getJieQiTable().items():
                clock = datetime.fromisoformat(solar.toYmdHms())
                utc = clock.replace(tzinfo=CHINA).astimezone(UTC)
                terms.setdefault(utc, name)
    return [(name, utc) for utc, name in sorted(terms.items())]


def _split_range(a, b, terms, zone, basis, longitude, true_solar):
    if a == b:
        return [(a, b)]
    edges = {a, b}
    edges.update(instant for _, instant in terms if a < instant < b)
    # Chinese lunar dates always change at fixed UTC+08 midnight, independently
    # of the adopted solar/civil day used by the day and hour pillars.
    china_day = a.astimezone(CHINA).date()
    while china_day <= b.astimezone(CHINA).date():
        midnight = datetime.combine(china_day, time(), CHINA).astimezone(UTC)
        if a < midnight < b:
            edges.add(midnight)
        china_day += timedelta(days=1)
    # Also preserve the original input clock's Gregorian date. It can change
    # inside a cell while the adopted true-solar clock remains in one hour.
    raw_first = supplied_clock(a, zone, basis, longitude)
    raw_last = supplied_clock(b, zone, basis, longitude)
    raw_day = raw_first.date() - timedelta(days=1)
    while raw_day <= raw_last.date() + timedelta(days=1):
        midnight = datetime.combine(raw_day, time())
        if basis == "true-solar-time":
            possible = [solar_to_utc(midnight, longitude)]
        else:
            try:
                possible = [left for left, _ in resolve_range(midnight, midnight + timedelta(microseconds=1),
                                                              zone, basis, longitude)]
            except ValueError:
                possible = []
        edges.update(instant for instant in possible if a < instant < b)
        raw_day += timedelta(days=1)
    first = chart_clock(a, zone, basis, longitude, true_solar)
    last = chart_clock(b, zone, basis, longitude, true_solar)
    day = first.date() - timedelta(days=1)
    while day <= last.date() + timedelta(days=1):
        for hour in (0, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23):
            target = datetime.combine(day, time(hour))
            if true_solar or basis == "true-solar-time":
                possible = [solar_to_utc(target, longitude)]
            else:
                try:
                    possible = [left for left, _ in resolve_range(target, target + timedelta(microseconds=1),
                                                                  zone, basis, longitude)]
                except ValueError:
                    possible = []
            edges.update(instant for instant in possible if a < instant < b)
        day += timedelta(days=1)
    # A lunar unknown-time range can straddle a civil DST change; retain offset
    # branches and skip no valid instant even if the local clock jumps.
    cursor, old = a, a.astimezone(zone).utcoffset()
    while cursor < b:
        stop = min(cursor + timedelta(hours=1), b)
        new = stop.astimezone(zone).utcoffset()
        if old != new:
            left, right = cursor, stop
            while (right - left).total_seconds() > 1:
                mid = left + timedelta(seconds=int((right - left).total_seconds()) // 2)
                if mid.astimezone(zone).utcoffset() == old:
                    left = mid
                else:
                    right = mid
            edges.add(right)
        old, cursor = new, stop
    ordered = sorted(edges)
    return list(zip(ordered, ordered[1:]))


def _yun_at(lib, instant, sect, gender, method, zone):
    lunar = _lunar_at(lib, instant.astimezone(CHINA))
    ec = _ec(lunar, sect)
    result = _yun(ec, gender, method)
    forward = result["direction"] == "forward"
    jie = lunar.getNextJie() if forward else lunar.getPrevJie()
    jie_clock = datetime.fromisoformat(jie.getSolar().toYmdHms()).replace(tzinfo=CHINA)
    delta = abs((jie_clock.astimezone(UTC) - instant).total_seconds())
    start = datetime.fromisoformat(result["start_solar"]).replace(tzinfo=CHINA)
    result.update({"real_birth_utc": instant.isoformat(), "calculation_clock": "fixed UTC+08",
        "jie": {"name": jie.getName(), "library_clock": jie_clock.isoformat(sep=" "),
                "utc": jie_clock.astimezone(UTC).isoformat(), "elapsed_seconds": delta},
        "start_solar_clock": "fixed UTC+08 calendar arithmetic of traditional age offset",
        "start_utc": start.astimezone(UTC).isoformat(),
        "start_local_civil": start.astimezone(zone).isoformat(sep=" "),
        "duration_note": "Jie endpoints refer to real instants. Method 1 discretizes traditional branch hours; method 2 truncates to whole library minutes.",
    })
    return result


def build_chart(date_value, time_value=None, *, calendar="solar", leap=False, sect=2,
                timezone=None, time_basis="local-clock", gender=None, yun_sect=1,
                longitude=None, true_solar=False, fold=None, shichen=None):
    """Build canonical v3. Unknown date/minute ranges and repeated clocks survive.

    ``time_basis`` describes the supplied input. ``true_solar`` requests a solar
    day/hour clock; an already-solar input is inverted, never corrected twice.
    """
    validate_shichen(shichen, time_value)
    y, m, d, clock = _parse_input(date_value, time_value, calendar, leap, sect,
                                 timezone, time_basis, gender, yun_sect)
    validate_options(timezone, time_basis, longitude, true_solar, fold)
    if fold is not None and clock is None and shichen is None:
        raise ValueError("--fold requires a supplied birth time; unknown time retains all ranges")
    root = get_resources()
    lib = calendar_library(root)
    zone_name = DEFAULT_TIMEZONE if timezone is None else timezone
    zone = load_zone(zone_name, root)
    metadata = timezone_metadata(root)
    precision = "shichen" if shichen is not None else "unknown" if clock is None else "second" if len(time_value) == 8 else "minute"
    try:
        ranges, china_day = _birth_ranges(lib, y, m, d, clock, calendar, leap, zone,
                                         time_basis, longitude, fold, precision, shichen)
    except (OverflowError, OSError) as exc:
        raise ValueError("Date is outside the supported real-time conversion range") from exc
    terms = _terms_near(lib, ranges)
    grouped, alternatives = {}, {}
    solar_days, lunar_dates = set(), set()
    solar_near_edge = False
    for a, b in ranges:
        for left, right in _split_range(a, b, terms, zone, time_basis, longitude, true_solar):
            # Exact seconds are evaluated as supplied; interval representatives
            # sit safely inside their cell to avoid floating-point solar edges.
            sample = left if left == right else left + min(timedelta(seconds=0.5), (right - left) / 2)
            chosen = chart_clock(sample, zone, time_basis, longitude, true_solar)
            p, real_lunar = _instant_pillars(lib, sample, chosen, sect)
            record = clock_record(sample, zone, time_basis, longitude, true_solar)
            offset_branch = record["utc_offset_seconds"]
            key = (*tuple(p[k] for k in PILLAR_KEYS), offset_branch)
            raw_clock = supplied_clock(sample, zone, time_basis, longitude)
            solar_label = raw_clock.date().isoformat()
            lunar_label = real_lunar.toString()
            solar_days.add(solar_label)
            lunar_dates.add(lunar_label)
            cell = {"start_utc": left.isoformat(), "end_utc": right.isoformat(),
                    "end_exclusive": left != right,
                    "original_start": supplied_clock(left, zone, time_basis, longitude).isoformat(sep=" "),
                    "original_end": supplied_clock(right, zone, time_basis, longitude).isoformat(sep=" "),
                    "solar": solar_label, "lunar": lunar_label}
            candidate = grouped.setdefault(key, {"sect": sect, "pillars": p, "details": build_details(p),
                "representative_times": [], "time": record, "time_ranges": [],
                "lunar": None, "lunar_candidates": [], "solar": None, "solar_candidates": [],
                "basis": "exact supplied second" if precision == "second" else
                         "possible time within supplied shichen, not an exact birth time" if precision == "shichen" else
                         "possible time within supplied minute/date, not a birth-time assertion"})
            candidate["representative_times"].append(raw_clock.isoformat(sep=" "))
            candidate["time_ranges"].append(cell)
            if lunar_label not in candidate["lunar_candidates"]:
                candidate["lunar_candidates"].append(lunar_label)
            if solar_label not in candidate["solar_candidates"]:
                candidate["solar_candidates"].append(solar_label)
            # An already-solar shichen's endpoints are supplied boundaries, not uncertain birth minutes.
            if precision != "shichen" or time_basis != "true-solar-time":
                solar_near_edge |= near_solar_boundary(sample, zone, time_basis, longitude, true_solar, sect)
            if chosen.hour == 23:
                other, _ = _instant_pillars(lib, sample, chosen, 3 - sect)
                if other != p:
                    alt_key = (*tuple(other[k] for k in PILLAR_KEYS), offset_branch)
                    alternative = alternatives.setdefault(alt_key, {"sect": 3 - sect, "pillars": other,
                        "details": build_details(other), "representative_times": [], "time": record,
                        "time_ranges": [], "lunar": None, "lunar_candidates": [],
                        "solar": None, "solar_candidates": [],
                        "basis": "alternative 23:00 day-change convention"})
                    alternative["representative_times"].append(raw_clock.isoformat(sep=" "))
                    alternative["time_ranges"].append(cell)
                    if lunar_label not in alternative["lunar_candidates"]:
                        alternative["lunar_candidates"].append(lunar_label)
                    if solar_label not in alternative["solar_candidates"]:
                        alternative["solar_candidates"].append(solar_label)
    candidates = list(grouped.values())
    for candidate in candidates + list(alternatives.values()):
        for field in ("lunar", "solar"):
            values = sorted(candidate[field + "_candidates"])
            candidate[field + "_candidates"] = values
            candidate[field] = values[0] if len(values) == 1 else None
    primary = {key: candidates[0]["pillars"][key] if len({c["pillars"][key] for c in candidates}) == 1 else None
               for key in PILLAR_KEYS}
    if precision == "unknown":
        primary["hour"] = None
    uncertainty = []
    if precision == "shichen":
        uncertainty.append({"code": "birth_time_shichen", "fields": ["time"],
            "detail": "Only the supplied two-hour branch interval is known; representatives do not assert a birth minute."})
        if shichen == "子":
            uncertainty.append({"code": "early_late_zi_unresolved", "fields": ["day", "hour"],
                "detail": "Both 00:00..01:00 and 23:00..24:00 on the supplied date are retained; early/late Zi is not inferred."})
    if precision == "unknown":
        uncertainty.append({"code": "unknown_birth_time", "fields": ["hour"],
            "detail": "Full valid date ranges are retained; candidate representatives do not assert a birth time."})
    differing = [key for key in PILLAR_KEYS if len({c["pillars"][key] for c in candidates}) > 1]
    if differing:
        uncertainty.append({"code": "within_input_precision", "fields": differing,
            "detail": "Pillars vary across valid input instants; unresolved primary fields are null."})
    calendar_fields = (["lunar"] if len(lunar_dates) > 1 else []) + (["solar"] if len(solar_days) > 1 else [])
    if calendar_fields:
        uncertainty.append({"code": "within_input_calendar_dates", "fields": calendar_fields,
            "detail": "Valid input instants span multiple calendar dates; scalar dates are null and complete date sets are retained."})
    # Same pillars do not resolve a repeated clock. Preserve both real branches.
    elapsed = sum((b - a).total_seconds() for a, b in ranges)
    repeated = clock is not None and len(ranges) > 1 and (precision == "second" or elapsed > 60.00001)
    if shichen is not None:
        wall_ranges = [(supplied_clock(a, zone, time_basis, longitude),
                        supplied_clock(b - timedelta(microseconds=1), zone, time_basis, longitude)) for a, b in ranges]
        repeated = any(max(a, c) <= min(b, d) for i, (a, b) in enumerate(wall_ranges) for c, d in wall_ranges[i + 1:])
    if repeated:
        uncertainty.append({"code": "ambiguous_clock_fold", "fields": [],
            "detail": "The supplied clock repeats. Both real UTC instants are retained; select --fold 0 or 1."})
    if alternatives:
        uncertainty.append({"code": "day_change_convention", "fields": ["day"],
            "detail": "At adopted 23:00, sect 1 and sect 2 give different days; alternatives are separate."})
    if timezone is None:
        uncertainty.append({"code": "timezone_default", "fields": [],
            "detail": "Asia/Shanghai is an explicit software default, not a timezone inferred from a city or birthplace."})
    if true_solar or time_basis == "true-solar-time":
        uncertainty.append({"code": "approximate_solar_clock", "fields": ["day", "hour"],
            "detail": SOLAR_MODEL["accuracy"]})
        if solar_near_edge:
            uncertainty.append({"code": "solar_clock_near_boundary", "fields": ["day", "hour"],
                "detail": "An adopted solar time is within 120 seconds of a day/hour boundary; verify with a precise ephemeris and longitude."})
    if precision == "unknown" and calendar == "solar" and time_basis != "true-solar-time" and elapsed < 86400:
        uncertainty.append({"code": "date_has_clock_gap", "fields": [],
            "detail": "The civil date contains nonexistent clock intervals; only valid real-time ranges are retained."})
    if precision == "minute" and calendar == "solar" and time_basis != "true-solar-time" and elapsed < 59.99999:
        uncertainty.append({"code": "minute_has_clock_gap", "fields": [],
            "detail": "Part of the supplied minute does not exist after a historical clock jump; only its valid subranges remain."})
    if precision == "shichen" and calendar == "solar" and time_basis != "true-solar-time" and elapsed < 7199.99999:
        uncertainty.append({"code": "shichen_has_clock_gap", "fields": [],
            "detail": "Only real instants in the supplied shichen survive a civil clock jump."})
    unique_day = next(iter(solar_days)) if len(solar_days) == 1 else None
    result = {
        "schema_version": 3,
        "input": {"date": date_value, "time": time_value, "calendar": calendar, "leap": leap,
                  "sect": sect, "timezone": timezone, "time_basis": time_basis,
                  "gender": gender, "yun_sect": yun_sect, "longitude": longitude,
                  "true_solar": true_solar, "fold": fold},
        "solar": unique_day, "solar_candidates": sorted(solar_days),
        "solar_year": int(unique_day[:4]) if unique_day else None,
        "chinese_calendar_solar_date": china_day.isoformat() if china_day else None,
        "lunar": next(iter(lunar_dates)) if len(lunar_dates) == 1 else None,
        "lunar_candidates": sorted(lunar_dates),
        "time_known": clock is not None or shichen is not None, "time_precision": precision,
        "time_context": {"timezone": zone_name, "timezone_source": "default" if timezone is None else "explicit",
            "timezone_inferred_from_location": False, "tzdata_version": metadata["iana_version"],
            "input_time_basis": time_basis,
            "chart_time_basis": "true-solar-time" if true_solar or time_basis == "true-solar-time" else time_basis,
            "library_timezone": "UTC+08:00", "calendar": "Chinese lunar calendar on fixed UTC+08 dates",
            "fold_status": "unresolved" if repeated else "selected" if fold is not None else "not_ambiguous",
            "valid_utc_ranges": [{"start": a.isoformat(), "end": b.isoformat(), "end_exclusive": a != b} for a, b in ranges],
            "solar_model": SOLAR_MODEL if true_solar or time_basis == "true-solar-time" else None},
        "convention": {"sect": sect, "day_change": "23:00" if sect == 1 else "00:00",
            "year_month": "real UTC instant converted to fixed UTC+08; exact Jie boundaries, year at Li Chun",
            "day_hour": "adopted chart clock; library hour stem uses next-day stem at 23:00 under both sects",
            "lunar_date": "China calendar at fixed UTC+08; overseas clock date is solved, not copied from lunar conversion"},
        "pillars": primary, "details": build_details(primary), "candidates": candidates,
        "convention_alternatives": list(alternatives.values()), "uncertainty": uncertainty,
        "solar_terms_on_date": [{"name": name,
             "library_clock": instant.astimezone(CHINA).replace(tzinfo=None).isoformat(sep=" "),
             "library_offset": "+08:00", "utc": instant.isoformat(),
             "local_civil_clock": instant.astimezone(zone).isoformat(sep=" "),
             "adopted_clock": chart_clock(instant, zone, time_basis, longitude, true_solar).isoformat(sep=" ")}
             for name, instant in terms if (instant.astimezone(CHINA).date() == china_day if china_day else
                 supplied_clock(instant, zone, time_basis, longitude).date() == date(y, m, d))],
        "corrections": {"timezone_conversion": True,
            "dst": any(c["time"]["dst_seconds"] != 0 for c in candidates),
            "true_solar_time": true_solar or time_basis == "true-solar-time",
            "timezone_role": "offline IANA historical offsets; no geographic inference",
            "solar_term_clock": "real UTC instant and library fixed UTC+08, independent of adopted day/hour clock"},
        "notes": ["Historical timezone records can be uncertain before standard civil time; UTC timestamps do not imply historical observational precision.",
                  "Calendar conversion and case counts do not establish predictive validity."],
        "yun": {"status": "not_calculated", "reason": "requires known time and explicit male/female traditional-rule input"},
    }
    if shichen is not None:
        result["input"]["shichen"] = shichen
        result["yun"] = {"status": "not_calculated", "birth_precision": precision,
            "reason": "Only a shichen interval is supplied; no exact yun start date or timestamp is asserted."}
    if clock is not None and gender is not None:
        if repeated or len(candidates) != 1:
            result["yun"] = {"status": "not_calculated", "reason": "multiple real-time/pillar candidates; resolve fold or boundary first"}
        else:
            # Use the original interval start, never a representative/noon clock.
            instant = ranges[0][0]
            result["yun"] = _yun_at(lib, instant, sect, gender, yun_sect, zone)
            result["yun"]["birth_precision"] = precision
            if precision == "minute":
                final = max(instant, ranges[-1][1] - timedelta(microseconds=1))
                end_yun = _yun_at(lib, final, sect, gender, yun_sect, zone)
                if result["yun"]["start_offset"] != end_yun["start_offset"]:
                    result["yun"] = {"status": "not_calculated",
                        "reason": "Valid instants in the supplied minute cross a yun discretization boundary; exact time is required.",
                        "endpoint_candidates": [result["yun"], end_yun]}
                else:
                    result["yun"]["start_utc_range"] = sorted([result["yun"]["start_utc"], end_yun["start_utc"]])
                    result["yun"]["precision_note"] = "Start timestamp shown at supplied-minute start; the full minute's endpoint range is retained in start_utc_range."
    return result


def write_json(value, output=None):
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        target = Path(output).expanduser().resolve()
        from output_paths import guard_output
        guard_output(target)
        # Deliberate caller path only: never save private birth data by default.
        protected = [Path(__file__).resolve().parents[1],
                     (Path(tempfile.gettempdir()) / "mingxue-master-cache").resolve()]
        protected.extend(Path(os.environ[name]).expanduser().resolve()
                         for name in ("MINGXUE_RESOURCE_DIR", "MINGXUE_CACHE_DIR") if os.environ.get(name))
        if any(target.is_relative_to(root) for root in protected):
            raise ValueError("User output must be outside the installed skill, resource and cache directories")
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(prefix="." + target.name + ".", dir=target.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    print(rendered, end="")


def add_birth_arguments(parser, *, required=False, optional_defaults=False):
    parser.add_argument("--date", required=required, help="YYYY-MM-DD")
    parser.add_argument("--time", help="HH:MM[:SS]; omitted means unknown")
    parser.add_argument("--shichen", choices=tuple(ZHI), help="known two-hour branch; mutually exclusive with --time")
    parser.add_argument("--calendar", choices=("solar", "lunar"), default=None if optional_defaults else "solar")
    parser.add_argument("--leap", action="store_true", default=None if optional_defaults else False)
    parser.add_argument("--sect", type=int, choices=(1, 2), default=None if optional_defaults else 2,
                        help="1=23:00 day change; 2=00:00 day change")
    parser.add_argument("--timezone", help="offline IANA zone key; omitted uses explicit Asia/Shanghai software default")
    parser.add_argument("--time-basis", choices=TIME_BASES, default=None if optional_defaults else "local-clock",
                        help="basis of the supplied clock; an already-solar clock is not corrected twice")
    parser.add_argument("--longitude", type=float, help="longitude degrees, east positive; required for solar time")
    parser.add_argument("--true-solar", action="store_true", default=None if optional_defaults else False,
                        help="calculate approximate apparent solar clock for day/hour pillars")
    parser.add_argument("--fold", type=int, choices=(0, 1), help="select earlier/later repeated instant; omitted retains both")
    parser.add_argument("--gender", choices=("male", "female"), help="optional traditional yun calculation input")
    parser.add_argument("--yun-sect", type=int, choices=(1, 2), default=None if optional_defaults else 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    add_birth_arguments(parser, required=True)
    parser.add_argument("--output", help="explicit JSON output path outside the skill")
    parser.add_argument("--json", action="store_true", help="JSON is also the default stdout format")
    args = parser.parse_args(argv)
    try:
        result = build_chart(args.date, args.time, calendar=args.calendar, leap=args.leap, sect=args.sect,
                             timezone=args.timezone, time_basis=args.time_basis, gender=args.gender, yun_sect=args.yun_sect,
                             longitude=args.longitude, true_solar=args.true_solar, fold=args.fold, shichen=args.shichen)
        write_json(result, args.output)
    except (ValueError, OSError, ResourceError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
