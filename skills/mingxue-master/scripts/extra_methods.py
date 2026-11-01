"""One JSON adapter for ten additional, separately identified methods."""
import argparse
import importlib
import json
import sys

sys.dont_write_bytecode = True
from workbench_catalog import EXTRA_MODULES


def calculate(system, params):
    if system not in EXTRA_MODULES or not isinstance(params, dict):
        raise ValueError("选择明确的方法，并提供参数对象。")
    module = importlib.import_module(EXTRA_MODULES[system])
    result = module.calculate(params) if system == "taiyi" else module.calculate(system, params)
    if not isinstance(result, dict) or result.get("system") != system:
        raise ValueError("计算结果与所选方法不一致。")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("system", choices=tuple(EXTRA_MODULES))
    parser.add_argument("--params", default="{}", help="explicit JSON parameter object")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.probe:
            module = importlib.import_module(EXTRA_MODULES[args.system])
            if args.system == "taiyi":
                value = module.probe()
            elif args.system in ("horary", "qizheng"):
                from astrology import probe
                value = probe()
            else:
                value = {"system": args.system, "status": "ready", "available": True, "network_access": False}
        else:
            value = calculate(args.system, json.loads(args.params))
        print(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return 3 if value.get("status") in ("error", "needs_setup", "engine_unavailable", "needs_input", "unsupported_date") else 0
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print(json.dumps({"system": args.system, "status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
