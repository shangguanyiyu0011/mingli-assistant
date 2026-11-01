"""Offline natal positions from physical UTC ranges; optional isolated engine.

No dependency installation or network request occurs in this module.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
import threading
import zipfile

sys.dont_write_bytecode = True
from chart import add_birth_arguments, build_chart, validate_shichen, write_json
from resources import ResourceError

ENGINE_PACKAGE = "pysweph"
ENGINE_VERSION = "2.10.3.6"
WHEEL_FILENAME = "pysweph-2.10.3.6-cp312-cp312-win_amd64.whl"
WHEEL_SHA256 = "0bb00ca91a6d9633376fcf20b62e654fceeb898e6dafc55e4ddd121d8f048d6f"
WHEEL_URL = ("https://files.pythonhosted.org/packages/c5/e7/"
             "2349ce769d00c8e3a963dc31335ed519c25e0bab3e2448e4ab0778e9f820/" + WHEEL_FILENAME)
SKILL_ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
_LOCK = threading.RLock()
SIGNS = ("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
         "Sagittarius", "Capricorn", "Aquarius", "Pisces")
SIGNS_ZH = ("白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座", "天秤座", "天蝎座",
            "射手座", "摩羯座", "水瓶座", "双鱼座")
BODIES = ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto")
HOUSE_SYSTEMS = {"P": "Placidus", "K": "Koch", "O": "Porphyry", "R": "Regiomontanus",
                 "C": "Campanus", "E": "Equal (Ascendant)", "W": "Whole sign"}
AYANAMSAS = {"lahiri": "SIDM_LAHIRI", "fagan-bradley": "SIDM_FAGAN_BRADLEY", "raman": "SIDM_RAMAN"}
NAKSHATRAS = ("Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
              "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra",
              "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha",
              "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati")
ASPECTS = (("conjunction", 0, 6), ("sextile", 60, 5), ("square", 90, 6),
           ("trine", 120, 6), ("opposition", 180, 6))


class EngineError(RuntimeError):
    pass


def default_engine_dir():
    from runtime_paths import engine_directory as persistent_engine_directory
    return persistent_engine_directory("astrology", ENGINE_VERSION)


def engine_directory(value=None):
    from runtime_paths import validate_external_directory
    return validate_external_directory(value or os.environ.get("MINGXUE_ASTRO_ENGINE") or default_engine_dir(), purpose="astrology engine")


def protected_roots():
    roots = [SKILL_ROOT, (Path(tempfile.gettempdir()) / "mingxue-master-cache").resolve()]
    roots.extend(Path(os.environ[name]).expanduser().resolve()
                 for name in ("MINGXUE_RESOURCE_DIR", "MINGXUE_CACHE_DIR") if os.environ.get(name))
    from output_paths import protected_output_roots
    roots.extend(protected_output_roots())
    return roots


def validate_engine_directory(path):
    from runtime_paths import validate_external_directory
    path = validate_external_directory(path, purpose="astrology engine")
    for parent in SKILL_ROOT.parents:
        if (parent / "plugin.json").is_file() or (parent / ".codex-plugin/plugin.json").is_file():
            if path.is_relative_to(parent) or parent.is_relative_to(path):
                raise ValueError("Engine directory must be outside the installed plugin")
            break
    return path


def _verify_engine(path):
    if sys.version_info[:2] != (3, 12) or sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise EngineError("The pinned prepared wheel requires CPython 3.12, Windows x86-64")
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise EngineError("Engine cache cannot be a symlink or junction")
    try:
        manifest = json.loads((path / "engine.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError("Pinned engine is not prepared; run prepare_astrology.py explicitly") from exc
    if (manifest.get("schema_version") != 1 or manifest.get("package") != ENGINE_PACKAGE
            or manifest.get("version") != ENGINE_VERSION or manifest.get("wheel_sha256") != WHEEL_SHA256):
        raise EngineError("Engine manifest does not match the pinned package/version/wheel")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise EngineError("Engine integrity manifest has no files")
    # Anchor the extraction to the fixed wheel, not a caller-editable manifest.
    try:
        wheel = path / WHEEL_FILENAME
        if wheel.is_symlink() or hashlib.sha256(wheel.read_bytes()).hexdigest() != WHEEL_SHA256:
            raise EngineError("Cached wheel SHA-256 does not match the fixed pin")
        with zipfile.ZipFile(wheel) as archive:
            expected = {member.filename: hashlib.sha256(archive.read(member)).hexdigest()
                        for member in archive.infolist() if not member.is_dir()}
        if expected != files:
            raise EngineError("Engine integrity manifest differs from the pinned wheel contents")
    except (OSError, zipfile.BadZipFile) as exc:
        raise EngineError("Pinned cached wheel is missing or invalid") from exc
    actual = set()
    python_dir = path / "python"
    if not python_dir.is_dir():
        raise EngineError("Prepared engine Python directory is missing")
    for item in python_dir.rglob("*"):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise EngineError("Engine files cannot be symlinks or junctions")
        if item.is_file():
            name = item.relative_to(python_dir).as_posix()
            actual.add(name)
            if files.get(name) != hashlib.sha256(item.read_bytes()).hexdigest():
                raise EngineError("Engine file hash mismatch: " + name)
    if actual != set(files):
        raise EngineError("Prepared engine file set differs from its manifest")
    distributions = list(importlib.metadata.distributions(path=[str(python_dir)]))
    if not any(d.metadata.get("Name", "").lower() == ENGINE_PACKAGE and d.version == ENGINE_VERSION for d in distributions):
        raise EngineError("Prepared wheel distribution metadata does not match its pin")
    return python_dir


def _load_engine(path):
    python_dir = _verify_engine(path)
    existing = sys.modules.get("swisseph")
    if existing is not None and not Path(existing.__file__).resolve().is_relative_to(python_dir):
        raise EngineError("Another swisseph is already imported; use a fresh Python process")
    sys.path.insert(0, str(python_dir))
    try:
        module = importlib.import_module("swisseph")
    except (ImportError, OSError) as exc:
        raise EngineError("Pinned native engine cannot load with this Python/OS: " + str(exc)) from exc
    finally:
        sys.path.remove(str(python_dir))
    if not Path(module.__file__).resolve().is_relative_to(python_dir):
        raise EngineError("Refusing a swisseph module outside the isolated engine directory")
    # Explicit Moshier below uses no external ephemeris files and never downloads.
    module.set_ephe_path(str(path / "ephemeris"))
    return module


def probe(engine_dir=None):
    """Return local integrity/load status only. Never install or access a network."""
    info = {"available": False, "package": ENGINE_PACKAGE, "version": ENGINE_VERSION,
            "ephemeris": "Moshier analytical ephemeris", "network_access": False,
            "required_runtime": "CPython 3.12 / Windows x86-64", "prepare_script": "scripts/prepare_astrology.py"}
    try:
        path = validate_engine_directory(engine_directory(engine_dir))
        info["engine_dir"] = str(path)
        with _LOCK:
            swe = _load_engine(path)
            # A real planetary computation catches unusable native libraries.
            xx, flags, warning = swe.calc_ut(2451545.0, swe.SUN, swe.FLG_MOSEPH | swe.FLG_SPEED)
            if not math.isfinite(xx[0]) or not flags & swe.FLG_MOSEPH:
                raise EngineError("Engine calculation did not use the requested analytical ephemeris")
            info.update(available=True, status="ready", library_version=str(swe.version),
                        self_check_sun_longitude=xx[0], warning=warning or None)
    except (EngineError, ValueError, OSError) as exc:
        info.update(status="engine_unavailable", reason=str(exc))
    return info


def longitude_record(value, *, sidereal=False):
    lon = value % 360.0
    sign = min(int(lon // 30), 11)
    result = {"longitude": lon, "sign_index": sign, "sign": SIGNS[sign], "sign_zh": SIGNS_ZH[sign],
              "degree_in_sign": lon - 30 * sign}
    if sidereal:
        part = lon * 27.0 / 360.0
        n = min(int(part), 26)
        result["nakshatra"] = {"index": n + 1, "name": NAKSHATRAS[n], "pada": min(int((part - n) * 4) + 1, 4),
                               "basis": "27 equal divisions of the explicitly selected sidereal ecliptic"}
    return result


def angular_distance(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def calculate_aspects(planets):
    result = []
    for i, a in enumerate(planets):
        for b in planets[i + 1:]:
            separation = angular_distance(a["longitude"], b["longitude"])
            for name, angle, allowed in ASPECTS:
                orb = abs(separation - angle)
                if orb <= allowed:
                    result.append({"body_a": a["name"], "body_b": b["name"], "aspect": name,
                                   "exact_angle": angle, "separation": separation, "orb": orb, "allowed_orb": allowed})
    return sorted(result, key=lambda item: (item["orb"], item["body_a"], item["body_b"]))


def _coordinate(value, name, bound):
    if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int))
                              or not math.isfinite(value) or not -bound <= value <= bound):
        raise ValueError(f"{name} must be a finite number in {-bound}..{bound}")
    return value


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("UTC range timestamps must be ISO strings")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid UTC range timestamp") from exc
    if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        raise ValueError("Chart ranges must contain physical UTC timestamps with +00:00 offsets")
    return instant.astimezone(UTC)


def validate_chart(chart_data):
    if (not isinstance(chart_data, dict) or chart_data.get("schema_version") != 3
            or type(chart_data.get("time_known")) is not bool):
        raise ValueError("--chart requires shared calendar schema_version 3 with explicit time_known")
    source = chart_data.get("input", {})
    if not isinstance(source, dict):
        raise ValueError("Chart input must be an object")
    validate_shichen(source.get("shichen"), source.get("time"))
    branch_precision = chart_data.get("time_precision") == "shichen"
    if branch_precision != (source.get("shichen") is not None) or branch_precision and not chart_data["time_known"]:
        raise ValueError("Shichen input must retain time_known=true and time_precision=shichen")
    ranges = chart_data.get("time_context", {}).get("valid_utc_ranges")
    if not isinstance(ranges, list) or not ranges or len(ranges) > 32:
        raise ValueError("Shared chart must retain valid_utc_ranges")
    parsed = []
    for record in ranges:
        if not isinstance(record, dict):
            raise ValueError("Invalid UTC range record")
        a, b = _utc(record.get("start")), _utc(record.get("end"))
        if b < a or (parsed and a < parsed[-1][1]):
            raise ValueError("UTC ranges must be ordered, non-overlapping and non-negative")
        if type(record.get("end_exclusive")) is not bool or record["end_exclusive"] != (a != b):
            raise ValueError("UTC range end_exclusive must distinguish intervals and exact instants")
        if chart_data["time_known"] and not branch_precision and (b - a).total_seconds() > 120:
            raise ValueError("Known-time chart interval exceeds supported minute precision")
        if (not chart_data["time_known"] or branch_precision) and a == b:
            raise ValueError("Unknown birth time must retain real UTC date intervals")
        parsed.append((a, b))
    if sum((b - a).total_seconds() for a, b in parsed) > 172800:
        raise ValueError("Birth date ranges exceed two physical days")
    return parsed


def _jd(swe, instant):
    # utc_to_jd handles the UTC -> TT / UT1 time-scale distinction; julday(UTC)
    # alone would silently treat a civil UTC clock as UT1.
    return swe.utc_to_jd(instant.year, instant.month, instant.day, instant.hour,
                         instant.minute, instant.second + instant.microsecond / 1e6, swe.GREG_CAL)


def _planet(swe, jdut, name, sidereal):
    flags = swe.FLG_MOSEPH | swe.FLG_SPEED | (swe.FLG_SIDEREAL if sidereal else 0)
    xx, actual, warning = swe.calc_ut(jdut, getattr(swe, name.upper()), flags)
    if not actual & swe.FLG_MOSEPH:
        raise EngineError("Unexpected ephemeris backend; refusing silent fallback")
    return {"name": name, **longitude_record(xx[0], sidereal=sidereal), "latitude": xx[1], "distance_au": xx[2],
            "longitude_speed_deg_per_day": xx[3], "retrograde": xx[3] < 0,
            "stationary_review": abs(xx[3]) < 0.0001, "returned_flags": actual, "engine_warning": warning or None}


def _houses(swe, jdut, latitude, longitude, system, sidereal):
    header = {"system_code": system, "system_name": HOUSE_SYSTEMS[system], "ascendant": None,
              "midheaven": None, "cusps": [], "automatic_fallback": False}
    if latitude is None or longitude is None:
        return {**header, "status": "not_calculated", "reason": "requires explicit latitude and longitude; no city/timezone inference"}
    if abs(latitude) == 90:
        return {**header, "status": "unavailable", "reason": "house geometry is undefined at a geographic pole"}
    try:
        cusps, axes = swe.houses_ex(jdut, latitude, longitude, system.encode("ascii"), swe.FLG_SIDEREAL if sidereal else 0)
        if len(cusps) != 13:
            raise EngineError("Pinned house API must return 13 cusps with an unused zero index")
        return {**header, "status": "calculated", "ascendant": longitude_record(axes[0], sidereal=sidereal),
                "midheaven": longitude_record(axes[1], sidereal=sidereal),
                "cusps": [{"house": i, **longitude_record(cusps[i], sidereal=sidereal)} for i in range(1, 13)]}
    except swe.Error as exc:
        return {**header, "status": "unavailable", "reason": f"Requested house system cannot be calculated here (including polar restrictions): {exc}"}


def _instant(swe, instant, latitude, longitude, system, sidereal, ayanamsa):
    jdtt, jdut = _jd(swe, instant)
    planets = [_planet(swe, jdut, name, sidereal) for name in BODIES]
    houses = _houses(swe, jdut, latitude, longitude, system, sidereal)
    if houses["status"] == "calculated":
        cusps = houses["cusps"]
        for planet in planets:
            for i, cusp in enumerate(cusps):
                arc = (cusps[(i + 1) % 12]["longitude"] - cusp["longitude"]) % 360
                if (planet["longitude"] - cusp["longitude"]) % 360 < arc:
                    planet["house_longitude_only"] = i + 1
                    break
    return {"utc": instant.isoformat(), "julian_day_tt": jdtt, "julian_day_ut1": jdut,
            "ayanamsa_degrees": swe.get_ayanamsa_ex_ut(jdut, swe.FLG_MOSEPH)[1] if sidereal else None,
            "ayanamsa_mean_degrees_without_nutation": swe.get_ayanamsa_ut(jdut) if sidereal else None,
            "planets": planets, "aspects": calculate_aspects(planets), "houses": houses}


def _sun_range(swe, start, end, sidereal):
    a = _planet(swe, _jd(swe, start)[1], "Sun", sidereal)
    b = _planet(swe, _jd(swe, end)[1], "Sun", sidereal)
    # The geocentric Sun is direct over the supported date range. Unwrap once
    # across 0 Aries so a day spanning Pisces/Aries retains both signs.
    span = (b["longitude"] - a["longitude"]) % 360
    if span > 2.0 or a["longitude_speed_deg_per_day"] <= 0 or b["longitude_speed_deg_per_day"] <= 0:
        raise EngineError("Sun interval is outside the supported direct-motion range")
    signs = [a["sign"]]
    crossings = []
    next_edge = (int(a["longitude"] // 30) + 1) * 30.0
    if next_edge <= a["longitude"] + span:
        left, right = start, end
        for _ in range(40):
            if (right - left).total_seconds() < 0.001:
                break
            mid = left + (right - left) / 2
            p = _planet(swe, _jd(swe, mid)[1], "Sun", sidereal)
            progress = (p["longitude"] - a["longitude"]) % 360
            if progress < next_edge - a["longitude"]:
                left = mid
            else:
                right = mid
        # An exclusive endpoint crossing does not establish the following sign
        # within the date interval, but its limiting position is still shown.
        if right < end - timedelta(milliseconds=1):
            signs.append(SIGNS[int(next_edge / 30) % 12])
            crossings.append({"boundary_longitude": next_edge % 360, "utc_bracket": [left.isoformat(), right.isoformat()],
                              "numerical_search_tolerance_seconds": 0.001})
    return {"start_utc": start.isoformat(), "end_utc": end.isoformat(), "end_exclusive": True,
            "longitude_start": a["longitude"], "longitude_end_limit": b["longitude"], "forward_span_degrees": span,
            "sign_candidates": signs, "sign_crossings": crossings,
            "interpretation": "continuous Sun interval, not an asserted birth instant; end position is an exclusive limit"}


def build_astrology(chart_data, *, latitude=None, longitude=None, house_system="P", zodiac="tropical",
                    ayanamsa=None, engine_dir=None):
    """Calculate exact candidates or conservative unknown-time Sun intervals."""
    ranges = validate_chart(chart_data)
    source_input = chart_data.get("input", {})
    if not isinstance(source_input, dict):
        raise ValueError("Chart input must be an object")
    original_lon = source_input.get("longitude")
    if longitude is not None and original_lon is not None and longitude != original_lon:
        raise ValueError("Longitude override conflicts with shared chart input; rebuild the shared chart with consistent coordinates")
    longitude = _coordinate(original_lon if longitude is None else longitude, "longitude", 180)
    latitude = _coordinate(source_input.get("latitude") if latitude is None else latitude, "latitude", 90)
    if house_system not in HOUSE_SYSTEMS:
        raise ValueError("house_system must be one of " + ", ".join(HOUSE_SYSTEMS))
    if zodiac not in ("tropical", "sidereal"):
        raise ValueError("zodiac must be tropical or sidereal")
    sidereal = zodiac == "sidereal"
    if sidereal and ayanamsa not in AYANAMSAS:
        raise ValueError("Sidereal zodiac requires explicit ayanamsa: " + ", ".join(AYANAMSAS))
    if not sidereal and ayanamsa is not None:
        raise ValueError("ayanamsa cannot be applied to a tropical chart")
    info = probe(engine_dir)
    result = {"schema_version": 1, "system": "astrology", "status": "engine_unavailable", "engine": info,
              "input": {**source_input, "latitude": latitude, "longitude": longitude},
              "source_chart": {"schema_version": 3, "input_hash": hashlib.sha256(json.dumps(
                  source_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()},
              "shared_chart_schema_version": 3, "time_known": chart_data["time_known"],
              "time_precision": chart_data.get("time_precision"), "time_context": chart_data["time_context"],
              "zodiac": {"type": zodiac, "ayanamsa": ayanamsa},
              "frame": "apparent geocentric ecliptic longitude of date (degrees)",
              "house_system": {"code": house_system, "name": HOUSE_SYSTEMS[house_system]},
              "aspect_policy": {"scope": "10 physical bodies only; ecliptic longitude separation",
                                "aspects": [{"name": n, "angle": a, "orb": o} for n, a, o in ASPECTS]},
              "candidates": [], "sun_ranges": [], "sun_sign": None,
              "limits": ["Astronomical positions do not validate personality, compatibility or future-event predictions.",
                         "No birthplace, timezone or coordinates are inferred from a city name.",
                         "Moshier analytical ephemeris is selected explicitly; no downloaded ephemeris data or silent backend fallback.",
                         "House membership, when present, uses ecliptic longitude sectors and ignores a planet's ecliptic latitude.",
                         "TT/UT1 conversion uses the pinned engine's leap-second table and Delta-T model; historical and future clock accuracy is limited."]}
    if not info["available"]:
        result["reason"] = info["reason"]
        return result
    if any(a.year < 1583 or b.year > 2999 for a, b in ranges):
        result.update(status="unsupported_date", reason="This prepared analytical mode supports Gregorian physical UTC years 1583..2999")
        return result
    with _LOCK:
        swe = _load_engine(engine_directory(engine_dir))
        swe.set_sid_mode(getattr(swe, AYANAMSAS[ayanamsa]) if sidereal else swe.SIDM_FAGAN_BRADLEY)
        try:
            if not chart_data["time_known"] or chart_data.get("time_precision") == "shichen":
                result["sun_ranges"] = [_sun_range(swe, a, b, sidereal) for a, b in ranges]
                signs = set(s for r in result["sun_ranges"] for s in r["sign_candidates"])
                result["sun_sign"] = next(iter(signs)) if len(signs) == 1 else None
                result.update(status="partial", mode="unknown_birth_time_sun_ranges",
                              reason="Unknown birth time: only continuous Sun intervals are calculated; no noon, Moon, ascendant, houses or exact aspects are asserted")
                if chart_data.get("time_precision") == "shichen":
                    result.update(mode="shichen_sun_ranges", reason="Only a shichen interval is known: continuous Sun intervals are retained; no exact birth minute, Moon, ascendant, houses or aspects are asserted")
            else:
                for a, b in ranges:
                    sample = _instant(swe, a, latitude, longitude, house_system, sidereal, ayanamsa)
                    sample.update(valid_utc_range={"start": a.isoformat(), "end": b.isoformat(), "end_exclusive": a != b},
                                  representative_only=a != b, sample_role="exact_instant" if a == b else "input_interval_start")
                    if a != b:
                        sample["end_limit"] = _instant(swe, b, latitude, longitude, house_system, sidereal, ayanamsa)
                        sample["precision_note"] = "The whole valid minute is retained; start and exclusive-end positions are samples, not an exact birth time"
                    result["candidates"].append(sample)
                signs = {c["planets"][0]["sign"] for c in result["candidates"]}
                signs.update(c["end_limit"]["planets"][0]["sign"] for c in result["candidates"] if "end_limit" in c)
                result["sun_sign"] = next(iter(signs)) if len(signs) == 1 else None
                result.update(status="calculated", mode="physical_utc_candidates")
        except swe.Error as exc:
            result.update(status="calculation_unavailable", reason=str(exc), candidates=[], sun_ranges=[], sun_sign=None)
    return result


def write_result(value, output=None, engine_dir=None):
    if output is not None:
        target = Path(output).expanduser().resolve()
        forbidden = [engine_directory(engine_dir), (Path(tempfile.gettempdir()) / "mingxue-engines").resolve()]
        if any(target.is_relative_to(root) for root in forbidden) or any(p.name == "engine-cache" for p in target.parents):
            raise ValueError("User output must be outside engine caches")
    write_json(value, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--probe", action="store_true", help="local engine check; no network/install")
    modes.add_argument("--chart", help="shared chart schema 3 JSON file")
    add_birth_arguments(parser, optional_defaults=True)
    parser.add_argument("--latitude", type=float, help="north-positive geographic latitude")
    parser.add_argument("--house-system", choices=tuple(HOUSE_SYSTEMS), default="P")
    parser.add_argument("--zodiac", choices=("tropical", "sidereal"), default="tropical")
    parser.add_argument("--ayanamsa", choices=tuple(AYANAMSAS))
    parser.add_argument("--engine-dir", help="isolated prepared engine directory")
    parser.add_argument("--output", help="explicit JSON output outside skill/resources/engine caches")
    parser.add_argument("--json", action="store_true", help="JSON is the default stdout format")
    args = parser.parse_args(argv)
    birth_keys = ("date", "time", "shichen", "calendar", "leap", "sect", "timezone", "time_basis", "true_solar", "fold", "gender", "yun_sect")
    try:
        if args.chart and args.output:
            source, output = Path(args.chart).resolve(), Path(args.output).resolve()
            if source == output or (source.exists() and output.exists() and source.samefile(output)):
                raise ValueError("output must not overwrite the shared input chart")
        if args.probe:
            if any(getattr(args, k) is not None for k in birth_keys) or args.longitude is not None or args.latitude is not None:
                raise ValueError("--probe cannot be combined with birth data")
            result = probe(args.engine_dir)
        else:
            if args.chart:
                if any(getattr(args, k) is not None for k in birth_keys):
                    raise ValueError("--chart cannot be combined with birth clock/calendar overrides")
                from case_lookup import load_chart
                chart_data = load_chart(args.chart)
            elif args.date:
                options = {k: getattr(args, k) for k in birth_keys if k not in ("date", "time") and getattr(args, k) is not None}
                chart_data = build_chart(args.date, args.time, longitude=args.longitude, **options)
            else:
                raise ValueError("Supply --probe, --chart JSON, or --date and explicit clock/timezone data")
            result = build_astrology(chart_data, latitude=args.latitude, longitude=args.longitude,
                                     house_system=args.house_system, zodiac=args.zodiac, ayanamsa=args.ayanamsa,
                                     engine_dir=args.engine_dir)
        write_result(result, args.output, args.engine_dir)
        return 0 if result.get("available") or result.get("status") in ("calculated", "partial") else 3
    except (ValueError, OSError, ResourceError, EngineError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
