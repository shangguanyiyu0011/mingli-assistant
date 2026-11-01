"""Taiyi year/month/day/hour boards through a fixed isolated calculation engine."""
from __future__ import annotations
import argparse
import contextlib
from datetime import date, datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
ENGINE_COMMIT = "11f78555d5e77c81ac8af69d243a981c22934733"
ENGINE_VERSION = "11f78555d5e7-py311-v1"
ENGINE_ABI = 1
MODES = {"year": 0, "month": 1, "day": 2, "hour": 3}
METHODS = {0: "太乙统宗", 1: "太乙金镜", 2: "太乙淘金歌", 3: "太乙局"}
ARTIFACTS = json.loads(r'''{"source":{"filename":"source-11f78555.zip","url":"https://api.github.com/repositories/271135869/zipball/11f78555d5e77c81ac8af69d243a981c22934733","sha256":"1fda0d4a6d370b69bb2e1b3ed9116bafb92752e5ebace7d97bfff09cb4447363","kind":"source"},"python":{"filename":"python-3.11.9-embed-amd64.zip","url":"https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip","sha256":"009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b","kind":"runtime"},"cn2an":{"filename":"cn2an-0.5.24-py3-none-any.whl","url":"https://files.pythonhosted.org/packages/8c/e6/f3436a83c6dddc306ee8d6cf7dc1b90a5a3496ae66d9392100c0c5c3f578/cn2an-0.5.24-py3-none-any.whl","sha256":"3d57d862a56133070ba6a737b8095bfc94716b41b7684e7a98d2d5b049495db7","version":"0.5.24","kind":"wheel"},"sxtwl":{"filename":"sxtwl-2.0.7-cp311-cp311-win_amd64.whl","url":"https://files.pythonhosted.org/packages/ac/6a/61eea689e14fe4cb1f79e23463b245573e9fcb85a3faab81d6ca279fe936/sxtwl-2.0.7-cp311-cp311-win_amd64.whl","sha256":"78405ee906adf7b36b07c8942da764646cf8a13b6ae4319f62cbb2aa1b765dd7","version":"2.0.7","kind":"wheel"},"bidict":{"filename":"bidict-0.24.1-py3-none-any.whl","url":"https://files.pythonhosted.org/packages/97/53/2a3c7d562271ec6b6e38e7216b3104899f8aa4180c0713cb8aaf69e29cd5/bidict-0.24.1-py3-none-any.whl","sha256":"fd3eaa737917d8a14f4baa391670c433c4e3f6f5fd2cd99d4bf436437f432364","version":"0.24.1","kind":"wheel"},"drawsvg":{"filename":"drawsvg-2.4.2-py3-none-any.whl","url":"https://files.pythonhosted.org/packages/15/5a/c47c10de42c49a3a9957123d77e5692b56b4fbc342b55285b52c41a8f1c1/drawsvg-2.4.2-py3-none-any.whl","sha256":"b1c101e187aa395cb13c039549e4f26fb7b7ee03974f53dc9798436463781bf1","version":"2.4.2","kind":"wheel"},"proces":{"filename":"proces-0.1.7-py3-none-any.whl","url":"https://files.pythonhosted.org/packages/6f/88/06cc0c7d890ed8d7e16ef0e56880dea516a21643fb1f3a69a50f4cc6f716/proces-0.1.7-py3-none-any.whl","sha256":"308325bbc96877263f06e57e5e9c760c4b42cc722887ad60be6b18fc37d68762","version":"0.1.7","kind":"wheel"},"ephem":{"filename":"ephem-4.2.1-cp311-cp311-win_amd64.whl","url":"https://files.pythonhosted.org/packages/06/14/0f64f5404916ff8d8dcf6452679431bd1daa2ea4a518a3a6f4e1bc1fa16a/ephem-4.2.1-cp311-cp311-win_amd64.whl","sha256":"42f298da8ce31c541ed0bf1c680d0b53015859bc3a8a99551b880b510bc8cac6","version":"4.2.1","kind":"wheel"},"typing_extensions":{"filename":"typing_extensions-4.16.0-py3-none-any.whl","url":"https://files.pythonhosted.org/packages/49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/typing_extensions-4.16.0-py3-none-any.whl","sha256":"481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8","version":"4.16.0","kind":"wheel"}}''')
# Nine containers are geographical presentation groups. Branch subpalaces stay labelled.
GRID = [(1, "乾", "西北", 0, 0, "戌乾亥"), (8, "子", "北", 0, 1, "子"), (3, "艮", "东北", 0, 2, "丑艮寅"),
        (6, "酉", "西", 1, 0, "酉"), (5, "中", "中", 1, 1, "中"), (4, "卯", "东", 1, 2, "卯"),
        (7, "坤", "西南", 2, 0, "未坤申"), (2, "午", "南", 2, 1, "午"), (9, "巽", "东南", 2, 2, "辰巽巳")]
RING = list("子丑艮寅卯辰巽巳午未坤申酉戌乾亥")

class TaiyiError(ValueError):
    def __init__(self, status, message, **details):
        super().__init__(message)
        self.status, self.details = status, details

def engine_directory(value=None):
    from runtime_paths import engine_directory as persistent, validate_external_directory
    supplied = value or os.environ.get("MINGXUE_TAIYI_ENGINE")
    return validate_external_directory(supplied) if supplied else persistent("taiyi", ENGINE_VERSION)

def archive_files(name, path):
    artifact = ARTIFACTS[name]
    path = Path(path)
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise TaiyiError("engine_integrity_error", f"固定引擎归档校验失败：{name}")
    files, seen, expanded = {}, set(), 0
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            rel = PurePosixPath(item.filename)
            if (rel.is_absolute() or any(p in ("", ".", "..") for p in rel.parts) or
                "\\" in item.filename or ":" in item.filename or
                (item.external_attr >> 16) & 0o170000 == 0o120000 or item.filename.casefold() in seen):
                raise TaiyiError("engine_integrity_error", "引擎归档含不安全或重复路径。")
            seen.add(item.filename.casefold())
            if item.is_dir():
                continue
            if artifact["kind"] == "source":
                if len(rel.parts) < 3 or rel.parts[1] != "src":
                    continue
                target = "python/" + "/".join(rel.parts[2:])
            else:
                target = ("runtime/" if artifact["kind"] == "runtime" else "python/") + item.filename
            expanded += item.file_size
            if expanded > 120_000_000 or item.file_size > 40_000_000:
                raise TaiyiError("engine_integrity_error", "引擎归档解压超过限制。")
            files[target] = archive.read(item)
    if not files:
        raise TaiyiError("engine_integrity_error", "引擎归档未包含预期文件。")
    return files

def verify_engine(directory):
    directory = Path(directory)
    marker = directory / "engine.json"
    if not marker.is_file():
        raise TaiyiError("needs_setup", "太乙引擎尚未准备；运行和探针不会自动联网。",
                         prepare_command=[sys.executable, "-X", "utf8", "-B", str(Path(__file__).with_name("prepare_taiyi.py")),
                                          "--engine-dir", str(directory)])
    try:
        manifest = json.loads(marker.read_text(encoding="utf-8"))
        if manifest.get("commit") != ENGINE_COMMIT or manifest.get("adapter_abi") != ENGINE_ABI:
            raise TaiyiError("engine_integrity_error", "太乙引擎版本或适配协议不符。")
        expected = {}
        for name, artifact in ARTIFACTS.items():
            for key, payload in archive_files(name, directory / "archives" / artifact["filename"]).items():
                if key.casefold() in {k.casefold() for k in expected}:
                    raise TaiyiError("engine_integrity_error", "引擎依赖文件冲突。")
                expected[key] = hashlib.sha256(payload).hexdigest()
        actual = {}
        for folder in ("runtime", "python"):
            root = directory / folder
            if root.is_symlink():
                raise TaiyiError("engine_integrity_error", "引擎目录不能是链接。")
            for path in root.rglob("*"):
                if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    raise TaiyiError("engine_integrity_error", "引擎文件不能是链接。")
                if path.is_file():
                    actual[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected != actual or manifest.get("files") != expected:
            raise TaiyiError("engine_integrity_error", "太乙引擎文件集或内容已改变，请显式修复。")
        return {"status": "verified", "commit": ENGINE_COMMIT, "file_count": len(actual), "network_access": False}
    except TaiyiError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        raise TaiyiError("engine_integrity_error", "太乙缓存缺失或损坏。") from exc

def validate_params(params):
    if not isinstance(params, dict):
        raise TaiyiError("invalid_input", "params 必须是 JSON 对象。")
    unknown = set(params) - {"date", "time", "mode", "method", "engine_dir", "timezone"}
    if unknown:
        raise TaiyiError("invalid_input", "不支持的参数：" + ", ".join(sorted(unknown)))
    d, t = params.get("date"), params.get("time")
    if not isinstance(d, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        raise TaiyiError("needs_input", "必须明确公历 date=YYYY-MM-DD。")
    try:
        parsed = date.fromisoformat(d)
    except ValueError as exc:
        raise TaiyiError("invalid_input", "无效公历日期。") from exc
    if not 1900 <= parsed.year <= 2100:
        raise TaiyiError("unsupported_range", "初版太乙适配验收范围仅公历1900..2100年。")
    if not isinstance(t, str) or not re.fullmatch(r"\d{2}:\d{2}", t):
        raise TaiyiError("needs_input", "必须明确 time=HH:MM；不默认补时辰。")
    try:
        clock = datetime.fromisoformat(d + "T" + t)
    except ValueError as exc:
        raise TaiyiError("invalid_input", "无效钟点。") from exc
    mode, method = params.get("mode", "year"), params.get("method", 1)
    if mode not in tuple(MODES):
        raise TaiyiError("unsupported_mode", "初版仅开放year/month/day/hour，分计和命法未开放。")
    if type(method) is not int or method not in METHODS:
        raise TaiyiError("invalid_input", "method 须为0/1/2/3。")
    zone = params.get("timezone", "Asia/Shanghai")
    if zone != "Asia/Shanghai":
        raise TaiyiError("unsupported_convention", "引擎采用中国UTC+08钟点，请先将目标日期时刻明确换算后再传入；不猜测境外时区。")
    return {"date": d, "time": t, "mode": mode, "method": method, "timezone": zone,
            "year": clock.year, "month": clock.month, "day": clock.day, "hour": clock.hour, "minute": clock.minute}

def _call_engine(directory, action, params=None):
    verify_engine(directory)
    command = [str(Path(directory) / "runtime/python.exe"), "-I", "-S", "-B", "-X", "utf8",
               str(Path(__file__).resolve()), "--worker"]
    request = {"action": action, "engine_dir": str(directory), "params": params}
    try:
        completed = subprocess.run(command, input=json.dumps(request, ensure_ascii=False), capture_output=True,
                                   encoding="utf-8", text=True, timeout=60, check=False)
        value = json.loads(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise TaiyiError("engine_error", f"隔离太乙进程未完成：{type(exc).__name__}") from exc
    if completed.returncode or value.get("status") != "ok":
        status = value.get("status") if value.get("status") in {"unsupported_boundary", "engine_integrity_error"} else "engine_error"
        raise TaiyiError(status, value.get("message", "太乙引擎执行失败。"))
    return value

def probe(engine_dir=None):
    try:
        directory = engine_directory(engine_dir)
        result = _call_engine(directory, "probe")
        return {"system": "taiyi", "status": "available", "available": True,
                "engine": {"commit": ENGINE_COMMIT, "version": ENGINE_VERSION, "abi": ENGINE_ABI,
                           "integrity": "verified", "runtime": result["runtime"]},
                "supported_modes": list(MODES), "methods": METHODS, "engine_dir": str(directory), "network_access": False}
    except TaiyiError as exc:
        return {"system": "taiyi", "status": exc.status, "available": False, "message": str(exc), **exc.details}
    except (ValueError, OSError) as exc:
        return {"system": "taiyi", "status": "invalid_input", "available": False, "message": str(exc)}

def _adapt(raw, params, accumulated, lunar):
    if not isinstance(raw, dict) or not isinstance(raw.get("局式"), dict):
        raise TaiyiError("engine_error", "太乙引擎缺少实际局式。")
    positions = raw.get("十六宮分佈")
    if not isinstance(positions, dict) or any(position not in positions for position in RING + ["中"]):
        raise TaiyiError("engine_error", "太乙引擎未提供完整十六宫及中宫神将。")
    for key in ("主算", "客算", "定算"):
        if not isinstance(raw.get(key), list) or not raw[key] or not isinstance(raw[key][0], (int, float)):
            raise TaiyiError("engine_error", f"太乙引擎缺少实际{key}。")
    doors = raw.get("八門分佈") or {}
    nine = []
    for number, name, direction, row, col, sub in GRID:
        children = [{"position": x, "stars": positions[x]} for x in sub]
        nine.append({"number": number, "name": name, "direction": direction, "row": row, "col": col,
                     "door": doors.get(str(number), doors.get(number)),
                     "stars": [{"name": star, "position": child["position"]} for child in children for star in child["stars"]],
                     "sub_palaces": children})
    technical_keys = ["太乙計", "太乙公式類別", "干支", "紀元", "太歲", "太乙落宮", "太乙", "天乙", "地乙",
                      "四神", "直符", "始擊", "主將", "主參", "客將", "客參", "合神", "計神", "定目",
                      "君基", "臣基", "民基", "八門值事"]
    technical = {k: raw[k] for k in technical_keys if k in raw}
    if isinstance(technical.get("干支"), list):
        technical["干支"] = technical["干支"][:4]  # Unaccepted minute-method data is not exposed.
    return {"bureau": raw["局式"], "accumulated_number": accumulated, "lunar": lunar,
            "host_count": raw["主算"][0], "guest_count": raw["客算"][0], "fixed_count": raw["定算"][0],
            "wenchang": raw.get("文昌", [None])[0], "positions": technical,
            "nine_palaces": nine, "sixteen_palaces": [{"position": x, "stars": positions[x]} for x in RING],
            "central_palace": {"position": "中", "stars": positions["中"]}}

def calculate(params):
    """Public API: calculate(params: dict) -> JSON-serializable result."""
    normalized = None
    try:
        normalized = validate_params(params)
        directory = engine_directory(params.get("engine_dir"))
        response = _call_engine(directory, "calculate", normalized)
        result = _adapt(response["raw"], normalized, response["accumulated"], response["lunar"])
        return {"system": "taiyi", "status": "ok", "input": {k: normalized[k] for k in ("date", "time", "mode", "method", "timezone")},
                "engine": {"commit": ENGINE_COMMIT, "version": ENGINE_VERSION, "abi": ENGINE_ABI, "integrity": "verified",
                           "runtime": response["runtime"]},
                "rules": {"mode": normalized["mode"], "ji_style": MODES[normalized["mode"]], "method": normalized["method"],
                          "method_name": METHODS[normalized["method"]], "calendar": "Gregorian date + engine Chinese lunar calendar",
                          "timezone": "fixed China UTC+08 adopted clock; no DST/solar/geographic inference",
                          "year_month": "积年/积月取引擎农历年/月；干支字段遵循固定历法实现，不能当作共享八字四柱",
                          "late_zi": "引擎干支23点按次日；积日/积时及农历字段另按固定实现，不作跨体系统一换日",
                          "grid": "北上南下；太乙宫数1乾2午3艮4卯5中6酉7坤8子9巽。九宫只是十六方位的可视容器，子宫标签保留",
                          "accumulation_adapter": "仅将引擎已经取整且数值精确的float积数转为int，修复索引类型，不改积数公式",
                          "ai_enabled": False, "game_theory_enabled": False},
                "chart": result, "nine_palaces": result["nine_palaces"],
                "limitations": ["初版只验收1900..2100年、年/月/日/时计；分计、命法、历史历法与全部流派未开放。",
                                "金镜时计遇上游零局边界时明确拒绝，不擅自改作六十局或切换其他算法。",
                                "太乙九宫编号不同于常见洛书编号；十六方位保持原标签，不能任意换宫或与其他术数合成同盘。",
                                "引擎的传统主客算与星将排布不构成预测有效性证明；不输出灾害/战争确定预言、匹配率或AI解读。"]}
    except TaiyiError as exc:
        return {"system": "taiyi", "status": exc.status, "input": normalized or params,
                "rules": {}, "limitations": [], "message": str(exc), **exc.details}
    except (ValueError, OSError) as exc:
        return {"system": "taiyi", "status": "invalid_input", "input": normalized or params,
                "rules": {}, "limitations": [], "message": str(exc)}

def _worker():
    try:
        request = json.load(sys.stdin)
        directory = Path(request["engine_dir"])
        verify_engine(directory)
        sys.path.insert(0, str(directory / "python"))
        with contextlib.redirect_stdout(io.StringIO()):
            from kintaiyi.kintaiyi import Taiyi
            import sxtwl
            class IntegralAccumulationTaiyi(Taiyi):
                def accnum(self, ji_style, taiyi_acumyear):
                    value = super().accnum(ji_style, taiyi_acumyear)
                    # The fixed day/method-3 formula uses round(..., 0), which
                    # returns an integral float, later used as a list index.
                    # Preserve its value while correcting that type mismatch.
                    if isinstance(value, float):
                        if not value.is_integer() or abs(value) >= 2 ** 53:
                            raise ValueError("积数不是可精确转换的整数，拒绝更改算法结果")
                        return int(value)
                    return value
            if request["action"] == "probe":
                instance = IntegralAccumulationTaiyi(2026, 3, 24, 12, 30)
                value = instance.kook(0, 1)
                if not isinstance(value, dict) or "數" not in value:
                    raise RuntimeError("引擎局式探针失败")
                result = {"status": "ok", "runtime": sys.version.split()[0]}
            else:
                p = request["params"]
                instance = IntegralAccumulationTaiyi(p["year"], p["month"], p["day"], p["hour"], p["minute"])
                if instance.kook(MODES[p["mode"]], p["method"]).get("數") == 0:
                    raise TaiyiError("unsupported_boundary", "固定引擎在该时刻产生零局，无法生成完整神将盘；请明确选择其他积年算法，未自动改盘。")
                raw = instance.pan(MODES[p["mode"]], p["method"], enable_game_theory=False)
                day = sxtwl.fromSolar(p["year"], p["month"], p["day"])
                lunar = {"year": day.getLunarYear(), "month": day.getLunarMonth(), "day": day.getLunarDay(), "is_leap": day.isLunarLeap()}
                result = {"status": "ok", "raw": raw, "lunar": lunar, "accumulated": instance.accnum(MODES[p["mode"]], p["method"]),
                          "runtime": sys.version.split()[0]}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": getattr(exc, "status", "engine_error"), "message": str(exc)}, ensure_ascii=False))
        return 2

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--params", help="JSON object")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--engine-dir")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return _worker()
    if args.probe:
        result = probe(args.engine_dir)
    else:
        try:
            params = json.loads(args.params) if args.params else {}
            if args.engine_dir:
                params["engine_dir"] = args.engine_dir
            result = calculate(params)
        except (ValueError, TypeError) as exc:
            result = {"system": "taiyi", "status": "invalid_input", "message": str(exc), "input": None, "rules": {}, "limitations": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("ok", "available") else 2

if __name__ == "__main__":
    raise SystemExit(main())

