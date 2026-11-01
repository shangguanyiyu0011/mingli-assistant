"""Chinese UTC+08 calendar-table lookup; not a personalized electional engine."""
import argparse
from datetime import date, time, timedelta
import json
import sys

sys.dont_write_bytecode = True
from chart import calendar_library, write_json
from resources import get_resources, ResourceError


def lookup(start, *, days=1, clock=None, topic=None):
    if type(days) is not int or not 1 <= days <= 31:
        raise ValueError("days must be an integer from 1 to 31")
    if not isinstance(start, str):
        raise ValueError("date must be YYYY-MM-DD")
    first = date.fromisoformat(start)
    if first.year < 1583:
        raise ValueError("calendar date lookup supports years 1583 and later")
    if topic is not None and (not isinstance(topic, str) or not topic.strip() or len(topic) > 30):
        raise ValueError("topic must be an exact short traditional calendar-table term")
    known = clock is not None
    if known:
        if not isinstance(clock, str):
            raise ValueError("time must be HH:MM[:SS]")
        selected = time.fromisoformat(clock)
        if selected.tzinfo is not None or selected.microsecond:
            raise ValueError("time must be an unzoned Chinese UTC+08 clock, without fractional seconds")
    else:
        selected = time(12)
    root = get_resources()
    lib = calendar_library(root)
    rows = []
    for n in range(days):
        current = first + timedelta(days=n)
        lunar = lib.Solar.fromYmdHms(current.year, current.month, current.day,
            selected.hour, selected.minute, selected.second).getLunar()
        yi, ji = lunar.getDayYi(1), lunar.getDayJi(1)
        row = {"date": current.isoformat(), "lunar": lunar.toString(),
               "day_pillar": lunar.getDayInGanZhiExact2(),
               "yi": yi, "ji": ji,
               "traditional_day_officer": lunar.getZhiXing(),
               "traditional_deity": {"name": lunar.getDayTianShen(),
                    "type": lunar.getDayTianShenType(), "label": lunar.getDayTianShenLuck()},
               "chong": lunar.getDayChongDesc(), "sha": lunar.getDaySha(),
               "hour_table": {"status": "not_calculated", "reason": "no time supplied"}}
        if known:
            row["hour_table"] = {"status": "calculated", "clock": clock,
                                  "day_change": "23:00 in the bundled time-table convention",
                                  "yi": lunar.getTimeYi(), "ji": lunar.getTimeJi()}
        if topic is not None:
            row["topic_lookup"] = {"term": topic, "listed_yi": topic in yi,
                                   "listed_ji": topic in ji,
                                   "semantics": "literal table membership, not a recommendation or outcome guarantee"}
        rows.append(row)
    return {"schema_version": 1, "system": "electional", "status": "ok",
            "capability": "calendar_table_only", "records": rows,
            "calendar_basis": {"calendar": "Chinese calendar tables", "clock": "fixed UTC+08",
                "day_change": "00:00", "day_table_month_boundary": "calendar date of Jie, sect=1; independent of supplied hour",
                "hour_known": known,
                "noon_placeholder": "used only for date-table lookup when no time is supplied; no hour result asserted"},
            "limitations": ["Not a personalized selection across electional schools.",
                "Traditional table labels do not establish real-world good/bad outcomes.",
                "Do not delay medical care or mandatory deadlines based on table entries."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--date")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--time")
    parser.add_argument("--topic")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.probe:
            if args.date or args.time or args.topic or args.output or args.days != 1:
                raise ValueError("--probe cannot be mixed with lookup inputs")
            result = {"system": "electional", "status": "available", "capability": "calendar_table_only"}
        else:
            if not args.date:
                raise ValueError("--date is required")
            result = lookup(args.date, days=args.days, clock=args.time, topic=args.topic)
        write_json(result, args.output)
        return 0
    except (ValueError, OSError, ResourceError, OverflowError) as exc:
        print(json.dumps({"system": "electional", "status": "error",
                          "error": {"code": "invalid_input", "message": str(exc)}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
