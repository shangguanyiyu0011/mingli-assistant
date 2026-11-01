"""Event-based Qizheng and horary structures using the isolated fixed engine."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
import math
import sys

sys.dont_write_bytecode = True
import astrology as astro
from chart import build_chart
from resources import ResourceError

SYSTEMS = ("qizheng", "horary")
SEVEN = ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn")
LABELS = {"Sun": "日", "Moon": "月", "Mercury": "水", "Venus": "金", "Mars": "火", "Jupiter": "木", "Saturn": "土",
          "Uranus": "天王星", "Neptune": "海王星", "Pluto": "冥王星"}
GLYPHS = dict(zip(astro.BODIES, ("☉", "☽", "☿", "♀", "♂", "♃", "♄", "♅", "♆", "♇")))
DOMICILE = ("Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter")
EXALTATION = {"Sun": 0, "Moon": 1, "Mercury": 5, "Venus": 11, "Mars": 9, "Jupiter": 3, "Saturn": 6}
PHASE_STEP_SECONDS = 60
PARAMETERS = {"date", "time", "timezone", "longitude", "latitude", "fold", "house_system", "zodiac", "ayanamsa", "engine_dir",
              "question", "quesited_house", "node_model", "node_orientation", "ziqi"}


def _rules(system):
    shared = {"time_source": "shared chart schema 3 physical UTC ranges; civil IANA clock, no implicit current time",
              "ephemeris": "pinned pysweph 2.10.3.6 / explicitly selected analytical ephemeris",
              "coordinates": "explicit geographic longitude east-positive and latitude north-positive",
              "position_frame": "apparent geocentric ecliptic longitude of date",
              "precision": "second inputs are instants; minute inputs retain start/exclusive-end samples; DST folds remain separate",
              "automatic_house_fallback": False}
    if system == "qizheng":
        shared.update(seven="Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn; physical bodies",
                      remainders="lunar node axis, mean lunar apogee, and optional explicit reference-cycle point; not four observable planets",
                      house_display="selected Western ecliptic house system as a visible reference; not a reconstruction of traditional Chinese branch-palace rules",
                      ziqi_default="not calculated without an explicit reference epoch/longitude/period; no historical phase is invented",
                      lunar_mansions="not calculated without an epoch/frame-specific 28-mansion boundary table")
    else:
        shared.update(dignity="seven classical bodies; sign-level domicile/exaltation/detriment/fall only; tropical zodiac",
                      aspect_orbs=[{"name": n, "angle": a, "orb": o} for n, a, o in astro.ASPECTS],
                      phase="local angular-error trend from real ephemeris positions at event +/-60 seconds; not a guarantee of future perfection",
                      house_default="R (Regiomontanus), an explicit interface default rather than a claim that all horary schools use it",
                      significators="first-house traditional ruler and Moon; quesited house only when the user explicitly selects it",
                      judgement="not generated")
    return shared


def _base(system, supplied):
    return {"schema_version": 1, "system": system, "status": "needs_input", "input": supplied,
            "rules": _rules(system), "limitations": [
                "Astronomical positions and traditional symbolic conventions do not validate predictions.",
                "No deterministic success/failure, death, medical or investment judgement is generated.",
                "No automatic location lookup, timezone inference, current-time substitution or engine download.",
                "House membership uses ecliptic longitude sectors and ignores body latitude; polar geometry requires review.",
                "The prepared engine mode supports physical UTC Gregorian years 1583..2999; numerical decimals do not imply clock accuracy."],
            "candidates": [], "wheel": None, "judgement": None}


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number in {low}..{high}")
    return value


def _validated(system, params):
    unknown = set(params) - PARAMETERS
    if unknown:
        raise ValueError("Unknown parameters: " + ", ".join(sorted(unknown)))
    p = dict(params)
    _number(p["longitude"], "longitude", -180, 180)
    _number(p["latitude"], "latitude", -90, 90)
    if not isinstance(p["timezone"], str) or not p["timezone"].strip():
        raise ValueError("timezone must be an explicit IANA zone key")
    p.setdefault("house_system", "W" if system == "qizheng" else "R")
    if p["house_system"] not in astro.HOUSE_SYSTEMS:
        raise ValueError("Unsupported house_system")
    p.setdefault("zodiac", "tropical")
    if p["zodiac"] not in ("tropical", "sidereal"):
        raise ValueError("zodiac must be tropical or sidereal")
    if system == "horary" and p["zodiac"] != "tropical":
        raise ValueError("This horary dignity ruleset requires the tropical zodiac")
    if p["zodiac"] == "sidereal" and p.get("ayanamsa") not in astro.AYANAMSAS:
        raise ValueError("sidereal mode requires an explicit supported ayanamsa")
    if p["zodiac"] == "tropical" and p.get("ayanamsa") is not None:
        raise ValueError("ayanamsa cannot be mixed into a tropical chart")
    if p.get("fold") is not None and (type(p["fold"]) is not int or p["fold"] not in (0, 1)):
        raise ValueError("fold must be 0 or 1")
    if p.get("question") is not None and (not isinstance(p["question"], str) or len(p["question"]) > 4000):
        raise ValueError("question must be text of at most 4000 characters")
    if system == "horary":
        if not p.get("question", "").strip():
            raise ValueError("horary requires the user's explicit question text")
        house = p.get("quesited_house")
        if house is not None and (type(house) is not int or not 1 <= house <= 12):
            raise ValueError("quesited_house must be an explicit integer 1..12")
    else:
        p.setdefault("node_model", "mean")
        p.setdefault("node_orientation", "ascending")
        if p["node_model"] not in ("mean", "true") or p["node_orientation"] not in ("ascending", "descending"):
            raise ValueError("node_model must be mean/true; node_orientation specifies ascending/descending Rahu")
        p.setdefault("ziqi", {"model": "not_calculated"})
        z = p["ziqi"]
        if not isinstance(z, dict) or z.get("model") not in ("not_calculated", "mean_cycle"):
            raise ValueError("ziqi.model must be not_calculated or mean_cycle")
        if z["model"] == "mean_cycle":
            if set(z) - {"model", "epoch_utc", "epoch_longitude", "period_days", "reference_label"}:
                raise ValueError("Unknown ziqi reference parameter")
            if not all(key in z for key in ("epoch_utc", "epoch_longitude", "period_days", "reference_label")):
                raise ValueError("ziqi mean_cycle requires explicit epoch_utc, epoch_longitude, period_days and reference_label")
            epoch = astro._utc(z["epoch_utc"])
            if not 1583 <= epoch.year <= 2999:
                raise ValueError("ziqi reference epoch must be 1583..2999 UTC")
            _number(z["epoch_longitude"], "ziqi.epoch_longitude", 0, 359.99999999999994)
            _number(z["period_days"], "ziqi.period_days", 1, 10_000_000)
            if not isinstance(z["reference_label"], str) or not z["reference_label"].strip() or len(z["reference_label"]) > 300:
                raise ValueError("ziqi reference_label must explicitly identify the chosen reference")
    return p


def dignities(planets):
    rows = []
    for planet in planets:
        name, sign = planet["name"], planet["sign_index"]
        if name not in SEVEN:
            continue
        labels = []
        if DOMICILE[sign] == name:
            labels.append("domicile")
        if EXALTATION[name] == sign:
            labels.append("exaltation")
        if DOMICILE[(sign + 6) % 12] == name:
            labels.append("detriment")
        if (EXALTATION[name] + 6) % 12 == sign:
            labels.append("fall")
        rows.append({"body": name, "label": LABELS[name], "sign": planet["sign"], "sign_index": sign, "dignities": labels,
                     "dignity_labels": [{"domicile": "入庙", "exaltation": "擢升", "detriment": "失势", "fall": "落陷"}[v] for v in labels],
                     "domicile_ruler": DOMICILE[sign], "exaltation_ruler": next((n for n, s in EXALTATION.items() if s == sign), None),
                     "unscored_factors": ["triplicity", "term", "face", "sect", "accidental dignity"],
                     "neutral_label": "no listed sign-level dignity; not a complete peregrine determination" if not labels else None})
    return rows


def _geometric_point(swe, jdut, body, sidereal):
    flags = swe.FLG_MOSEPH | swe.FLG_SPEED | (swe.FLG_SIDEREAL if sidereal else 0)
    values, actual, warning = swe.calc_ut(jdut, body, flags)
    if not actual & swe.FLG_MOSEPH:
        raise astro.EngineError("Unexpected backend for the calculated orbital point")
    return {**astro.longitude_record(values[0], sidereal=sidereal), "longitude_speed_deg_per_day": values[3],
            "retrograde": values[3] < 0, "returned_flags": actual, "engine_warning": warning or None}


def _remainders(swe, sample, p):
    sidereal = p["zodiac"] == "sidereal"
    north = _geometric_point(swe, sample["julian_day_ut1"], swe.MEAN_NODE if p["node_model"] == "mean" else swe.TRUE_NODE, sidereal)
    rahu_lon = (north["longitude"] + (180 if p["node_orientation"] == "descending" else 0)) % 360
    rahu = {**north, **astro.longitude_record(rahu_lon, sidereal=sidereal), "id": "Rahu", "label": "罗睺",
            "glyph": "☊" if p["node_orientation"] == "ascending" else "☋",
            "kind": "calculated_point", "status": "calculated", "observable_body": False,
            "algorithm": {"model": p["node_model"] + "_lunar_node", "orientation": p["node_orientation"],
                          "mapping_is_convention": True, "api_body": "MEAN_NODE" if p["node_model"] == "mean" else "TRUE_NODE"}}
    ketu = {**north, **astro.longitude_record((rahu_lon + 180) % 360, sidereal=sidereal), "id": "Ketu", "label": "计都",
            "glyph": "☋" if p["node_orientation"] == "ascending" else "☊",
            "kind": "calculated_point", "status": "calculated", "observable_body": False,
            "algorithm": {"model": "opposite_selected_Rahu", "formula": "(Rahu_longitude + 180) modulo 360",
                          "orientation": "descending" if p["node_orientation"] == "ascending" else "ascending"}}
    apogee = _geometric_point(swe, sample["julian_day_ut1"], swe.MEAN_APOG, sidereal)
    yuebo = {**apogee, "id": "Yuebo", "label": "月孛", "glyph": "⚸", "kind": "calculated_point", "status": "calculated",
             "observable_body": False, "algorithm": {"model": "mean_lunar_apogee", "api_body": "MEAN_APOG",
                "mapping_is_convention": True, "note": "modern orbital reference; not a claim to reproduce every historical uniform-motion table"}}
    reference = p["ziqi"]
    ziqi = {"id": "Ziqi", "label": "紫气", "glyph": "✶", "kind": "conventional_point", "observable_body": False,
            "status": "not_calculated", "longitude": None,
            "algorithm": {"model": reference["model"], "calibration": "no historical phase has been assumed"}}
    if reference["model"] == "mean_cycle":
        epoch = astro._utc(reference["epoch_utc"])
        epoch_tt = astro._jd(swe, epoch)[0]
        speed = 360.0 / reference["period_days"]
        lon = (reference["epoch_longitude"] + speed * (sample["julian_day_tt"] - epoch_tt)) % 360
        ziqi.update(**astro.longitude_record(lon, sidereal=sidereal), status="calculated_by_convention",
                    longitude_speed_deg_per_day=speed, retrograde=False,
                    algorithm={**reference, "epoch_julian_day_tt": epoch_tt, "reference_frame": p["zodiac"],
                               "ayanamsa": p.get("ayanamsa"), "day_basis": "TT days of 86400 SI seconds",
                               "formula": "(epoch_longitude + 360*(event_JD_TT-epoch_JD_TT)/period_days) modulo 360",
                               "calibration": "explicit user reference; historical school phase not independently verified"})
    return [rahu, ketu, yuebo, ziqi]


def _phased_aspects(swe, sample):
    current = [p for p in sample["planets"] if p["name"] in SEVEN]
    instant = astro._utc(sample["utc"])
    endpoints = []
    for delta in (-PHASE_STEP_SECONDS, PHASE_STEP_SECONDS):
        jdut = astro._jd(swe, instant + timedelta(seconds=delta))[1]
        endpoints.append({n: astro._planet(swe, jdut, n, False)["longitude"] for n in SEVEN})
    result = []
    for aspect in astro.calculate_aspects(current):
        a, b, exact = aspect["body_a"], aspect["body_b"], aspect["exact_angle"]
        errors = [abs(astro.angular_distance(e[a], e[b]) - exact) for e in endpoints]
        change = (errors[1] - errors[0]) / (2 * PHASE_STEP_SECONDS / 86400)
        phase = "exact" if aspect["orb"] <= 0.00001 else "applying" if change < -0.000001 else "separating" if change > 0.000001 else "stationary_or_turning"
        result.append({**aspect, "label": {"conjunction": "合相", "sextile": "六合", "square": "刑", "trine": "拱", "opposition": "冲"}[aspect["aspect"]],
                       "phase": phase, "phase_label": {"applying": "入相", "separating": "出相", "exact": "精确相位", "stationary_or_turning": "近停滞或转向"}[phase],
                       "orb_change_deg_per_day": change,
                       "sampling_seconds_each_side": PHASE_STEP_SECONDS, "local_trend_only": True})
    return result


def _wheel(points, houses, aspects):
    wheel_houses = copy.deepcopy(houses)
    asc = (houses.get("ascendant") or {}).get("longitude")
    anchor = asc if asc is not None else 0.0
    plotted = []
    for point in points:
        item = copy.deepcopy(point)
        item["screen_angle_deg"] = (180 - (item["longitude"] - anchor)) % 360 if item.get("longitude") is not None else None
        item["plot_style"] = "dashed" if item["kind"] == "conventional_point" else "hollow" if item["kind"] == "calculated_point" else "solid"
        plotted.append(item)
    for cusp in wheel_houses.get("cusps", []):
        cusp["screen_angle_deg"] = (180 - (cusp["longitude"] - anchor)) % 360
    return {"type": "ecliptic_wheel", "unit": "degrees", "anchor_longitude": anchor,
            "orientation": {"anchor": "Ascendant at left" if asc is not None else "0 Aries at left; ascendant unavailable",
                            "screen_axes": "x right, y down", "formula": "(180-(longitude-anchor_longitude)) modulo 360"},
            "points": plotted, "houses": wheel_houses, "aspects": aspects,
            "zodiac_signs": [{"index": i, "name": name, "label": astro.SIGNS_ZH[i], "start_longitude": 30 * i,
                              "screen_angle_deg": (180 - (30 * i - anchor)) % 360} for i, name in enumerate(astro.SIGNS)]}


def _assign_houses(points, houses):
    """Respect clockwise cusp order at polar Regiomontanus/Campanus sites."""
    cusps = houses.get("cusps", [])
    direction = None
    if len(cusps) == 12:
        for sign in (1, -1):
            widths = [(sign * (cusps[(i + 1) % 12]["longitude"] - cusp["longitude"])) % 360 for i, cusp in enumerate(cusps)]
            if abs(sum(widths) - 360) < 0.000001:
                direction = sign
                break
    houses["longitude_sector_direction"] = "counterclockwise_zodiac" if direction == 1 else "clockwise_zodiac" if direction == -1 else "unavailable"
    houses["position_method"] = "directed ecliptic cusp sectors; ignores point latitude"
    for point in points:
        point.pop("house_longitude_only", None)
        if direction is None or point.get("longitude") is None:
            continue
        for i, cusp in enumerate(cusps):
            if (direction * (point["longitude"] - cusp["longitude"])) % 360 < widths[i]:
                point["house_longitude_only"] = i + 1
                break


def _candidate(swe, sample, system, p):
    bodies = [{**copy.deepcopy(v), "id": v["name"], "label": LABELS[v["name"]], "glyph": GLYPHS[v["name"]],
               "kind": "physical_body", "status": "calculated", "traditional_seven": v["name"] in SEVEN} for v in sample["planets"]]
    result = {"utc": sample["utc"], "julian_day_tt": sample["julian_day_tt"], "julian_day_ut1": sample["julian_day_ut1"],
              "ayanamsa_degrees": sample.get("ayanamsa_degrees"), "houses": copy.deepcopy(sample["houses"]),
              "bodies": bodies if system == "horary" else [v for v in bodies if v["traditional_seven"]]}
    if system == "qizheng":
        result["four_remainders"] = _remainders(swe, sample, p)
        result["lunar_mansions"] = {"status": "not_calculated", "reason": "requires a verified epoch/frame-specific 28-mansion boundary table"}
        aspects = astro.calculate_aspects(result["bodies"])
        points = result["bodies"] + result["four_remainders"]
    else:
        result["dignities"] = dignities(bodies)
        aspects = _phased_aspects(swe, sample)
        points = bodies
        house_map = {v["house"]: v for v in sample["houses"].get("cusps", [])}
        def ruler(house):
            cusp = house_map.get(house)
            return {"house": house, "sign": cusp["sign"], "ruler": DOMICILE[cusp["sign_index"]]} if cusp else None
        result["significators"] = {"querent": ruler(1), "moon_cosignificator": "Moon", "quesited": ruler(p["quesited_house"]) if p.get("quesited_house") else None,
                                   "quesited_assignment": "explicit user choice" if p.get("quesited_house") else "not inferred from question text"}
    result["aspects"] = aspects
    _assign_houses(points, result["houses"])
    result["wheel"] = _wheel(points, result["houses"], aspects)
    return result


def calculate(system, params):
    """JSON-in/JSON-out; no file writes, network, dependency install or verdict."""
    try:
        supplied = json.loads(json.dumps(params, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError):
        supplied = {}
        result = _base(system, supplied)
        result.update(status="invalid_input", message="params must be a finite JSON object")
        return result
    result = _base(system, supplied if isinstance(supplied, dict) else {})
    if system not in SYSTEMS or not isinstance(supplied, dict):
        result.update(status="invalid_input", message="system must be qizheng/horary and params must be an object")
        return result
    required = ("date", "time", "timezone", "longitude", "latitude") + (("question",) if system == "horary" else ())
    missing = [k for k in required if supplied.get(k) is None or supplied.get(k) == ""]
    if missing:
        result.update(required=missing, message="Event time, timezone and coordinates must be explicit; no default noon or location")
        return result
    try:
        p = _validated(system, supplied)
        result["input"] = p
        shared = build_chart(p["date"], p["time"], timezone=p["timezone"], longitude=p["longitude"], fold=p.get("fold"))
        base = astro.build_astrology(shared, latitude=p["latitude"], longitude=p["longitude"],
                                     house_system=p["house_system"], zodiac=p["zodiac"], ayanamsa=p.get("ayanamsa"), engine_dir=p.get("engine_dir"))
        result.update(engine=base["engine"], source_chart=base["source_chart"], time_context=base["time_context"],
                      time_precision=base["time_precision"], zodiac=base["zodiac"], uncertainty=shared["uncertainty"])
        if base["status"] not in ("calculated", "partial"):
            result.update(status=base["status"], message=base.get("reason"))
            return result
        with astro._LOCK:
            swe = astro._load_engine(astro.engine_directory(p.get("engine_dir")))
            swe.set_sid_mode(getattr(swe, astro.AYANAMSAS[p["ayanamsa"]]) if p["zodiac"] == "sidereal" else swe.SIDM_FAGAN_BRADLEY)
            try:
                for sample in base["candidates"]:
                    row = _candidate(swe, sample, system, p)
                    row.update(valid_utc_range=sample["valid_utc_range"], representative_only=sample["representative_only"], sample_role=sample["sample_role"])
                    if sample.get("end_limit"):
                        row["end_limit"] = _candidate(swe, sample["end_limit"], system, p)
                    result["candidates"].append(row)
            except swe.Error as exc:
                raise astro.EngineError("Astral point/aspect calculation failed: " + str(exc)) from exc
        partial = len(result["candidates"]) != 1 or any(c["representative_only"] or c["houses"]["status"] != "calculated" for c in result["candidates"])
        if system == "qizheng":
            partial = partial or p["ziqi"]["model"] == "not_calculated"
            result["limitations"].extend(["Chinese mansion degrees and traditional branch-palace reconstruction are not supplied.",
                "Rahu/Ketu direction mapping and mean/true node selection are conventions shown in input and point metadata.",
                "A supplied Ziqi cycle is an explicitly calibrated-by-user mathematical reference, not an observable body or a verified historical school table.",
                "The analytical true-node model has a different accuracy limit from physical planetary positions; sub-arcsecond accuracy is not claimed."])
        else:
            result["limitations"].append("Triplicity, terms, faces, complete reception/perfection, void-of-course and final horary judgements are not calculated.")
        result["status"] = "partial" if partial else "calculated"
        if len(result["candidates"]) == 1:
            result["wheel"] = result["candidates"][0]["wheel"]
        else:
            result["message"] = "Multiple physical UTC candidates remain; select fold rather than choosing the first wheel"
        return result
    except (ValueError, OSError, ResourceError, astro.EngineError) as exc:
        result.update(status="invalid_input" if isinstance(exc, ValueError) else "calculation_unavailable", message=str(exc))
        result["candidates"], result["wheel"] = [], None
        return result


def probe(system=None, engine_dir=None):
    return {"schema_version": 1, "system": system, "systems": list(SYSTEMS), "engine": astro.probe(engine_dir),
            "scope": "local astronomical engine only; traditional conventions and references are separate", "network_access": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("system", nargs="?", choices=SYSTEMS)
    parser.add_argument("--params", help="JSON object with explicit event data")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--engine-dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.probe:
        if args.params is not None:
            parser.error("--probe cannot be combined with event params")
        result = probe(args.system, args.engine_dir)
        code = 0 if result["engine"]["available"] else 3
    else:
        if not args.system:
            parser.error("Supply a system or --probe")
        try:
            params = json.loads(args.params) if args.params is not None else {}
            if args.engine_dir:
                if not isinstance(params, dict) or params.get("engine_dir") not in (None, args.engine_dir):
                    raise ValueError("engine-dir conflicts with params")
                params["engine_dir"] = args.engine_dir
            result = calculate(args.system, params)
        except (ValueError, TypeError) as exc:
            result = {**_base(args.system, {}), "status": "invalid_input", "message": str(exc)}
        code = 0 if result["status"] in ("calculated", "partial") else 3
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
