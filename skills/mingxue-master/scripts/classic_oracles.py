"""Offline complete classical-text lookup with explicit, reproducible casting rules."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sys

from iching import hexagram, validate_lines

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "assets" / "classic-oracles"
DATA_HASHES = {
    "yilin": "f3e2b049dfd877cfb8e460d203954b169cc66705aad3127726d53bb7d97c4a0c",
    "lingqijing": "cb3508e23ee1aa440ba5bc9c97f9dcc1ec616df209c69ba86d5abff9491a1f2f",
}
_CACHE = {}
_BIT_INDEX = {}
_ALGORITHM = "classic-oracles-sha256-bits-v1"
_LIMITS = ["原典文本与传统符号用于文化阅读和反思，不是已经验证的个人预测。",
           "古籍中的病、生死、官讼等语句是历史引文，不用于疾病诊断、寿命判断或替代医疗、法律和财务决策。",
           "文本保留所选版本原字及显式校记，未经逐页影印校勘；全量索引不等于没有版本异文或转录讹字。"]


class OracleError(ValueError):
    pass


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise OracleError("Input must be finite, bounded JSON") from exc


def _load(system):
    if system not in DATA_HASHES:
        raise OracleError("system must be yilin or lingqijing")
    try:
        raw = (DATA_DIR / (system + ".json")).read_bytes()
    except OSError as exc:
        raise OracleError("Required local classical text is missing") from exc
    if hashlib.sha256(raw).hexdigest() != DATA_HASHES[system]:
        raise OracleError("Classical text integrity check failed")
    if system not in _CACHE:
        data = json.loads(raw)
        if data.get("schema_version") != 1 or data.get("system") != system:
            raise OracleError("Unexpected classical text schema")
        entries = data.get("entries")
        if not isinstance(entries, list) or len(entries) != (4096 if system == "yilin" else 125):
            raise OracleError("Classical text entry count is incomplete")
        if any(not isinstance(item.get("text"), str) or not item["text"] for item in entries):
            raise OracleError("Classical text has an empty primary entry")
        if system == "yilin":
            index = {(item["base"], item["changed"]): item for item in entries}
            expected = {(a,b) for a in range(1,65) for b in range(1,65)}
        else:
            index = {tuple(item["counts"]): item for item in entries}
            expected = {(a,b,c) for a in range(5) for b in range(5) for c in range(5)}
        if set(index) != expected:
            raise OracleError("Classical text has missing or duplicate lookup coordinates")
        _CACHE[system] = (data, index)
    return _CACHE[system]


def probe():
    systems = {}
    for system in DATA_HASHES:
        data, _ = _load(system)
        systems[system] = {"entries": len(data["entries"]), "edition": data["edition"],
                           "sha256": DATA_HASHES[system], "primary_text_missing": 0}
    return {"schema_version": 1, "status": "ready", "systems": systems, "network": "not_used",
            "requires_birth_data": False, "limitations": list(_LIMITS)}


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise OracleError(label + " must be an integer in " + str(low) + ".." + str(high))
    return value


def _seed(value):
    if isinstance(value, str):
        if not re.fullmatch(r"0|[1-9][0-9]{0,77}", value):
            raise OracleError("seed string must be a canonical nonnegative decimal integer")
        value = int(value)
    return _integer(value, 0, 2**256-1, "seed")


def _sample_bits(system, seed, count):
    supplied = seed is not None
    value = _seed(seed) if supplied else secrets.randbits(128)
    bits, counter = [], 0
    while len(bits) < count:
        block = hashlib.sha256(f"{_ALGORITHM}|{system}|{value}|{counter}".encode("ascii")).digest()
        bits.extend((byte >> shift) & 1 for byte in block for shift in range(7,-1,-1))
        counter += 1
    return bits[:count], {"source": "virtual_independent_fair_binary_sampling", "algorithm": _ALGORITHM,
                         "seed": str(value), "seed_origin": "caller_supplied" if supplied else "generated_by_secrets",
                         "binary_outcomes": bits[:count], "bits_used": count,
                         "reproducible": True, "physical_cast_observed": False}


def _params(system, params):
    if not isinstance(params, dict) or len(_canonical(params)) > 1_000_000:
        raise OracleError("params must be a JSON object no larger than 1 MB")
    defaults = {"yilin": "pair", "lingqijing": "counts"}
    method = params.get("method", defaults[system])
    choices = {"yilin": {"pair": {"base", "changed"}, "lines": {"lines"},
                         "coins": {"seed"}, "iching": {"iching_result"}},
               "lingqijing": {"counts": {"counts"}, "pieces": {"pieces"}, "toss": {"seed"}}}
    if not isinstance(method, str) or method not in choices[system]:
        raise OracleError("Unsupported method for " + system)
    if set(params) - (choices[system][method] | {"method", "question"}):
        raise OracleError("Unknown or incompatible parameters for method " + method)
    question = params.get("question", "")
    if not isinstance(question, str) or len(question) > 4000:
        raise OracleError("question must be a string of at most 4000 characters")
    return method, question


def _six_lines(values):
    if not isinstance(values, list) or len(values) != 6 or any(type(x) is not int or x not in (6,7,8,9) for x in values):
        raise OracleError("lines requires exactly six 6/7/8/9 values, bottom to top")
    validate_lines(values)
    return list(values)


def _from_lines(values):
    values = _six_lines(values)
    base_bits = [v % 2 for v in values]
    changed_bits = [1-b if v in (6,9) else b for b,v in zip(base_bits,values)]
    return hexagram(base_bits)["number"], hexagram(changed_bits)["number"], base_bits, changed_bits


def _number_bits(number):
    if not _BIT_INDEX:
        for encoded in range(64):
            bits=[(encoded >> i) & 1 for i in range(6)]
            _BIT_INDEX[hexagram(bits)["number"]]=bits
    return list(_BIT_INDEX[number])


def _iching_input(value):
    if (not isinstance(value, dict) or value.get("system") != "iching" or type(value.get("schema_version")) is not int or value.get("schema_version") != 1
            or value.get("ok") is not True or not isinstance(value.get("lines_bottom_to_top"), list)):
        raise OracleError("iching_result must be a complete successful iching payload, not a birth chart or wrapper")
    rows = value["lines_bottom_to_top"]
    if len(rows) != 6 or any(not isinstance(row,dict) or type(row.get("position")) is not int or row["position"] != i+1 for i,row in enumerate(rows)):
        raise OracleError("iching_result line positions must be 1..6, bottom to top")
    values = _six_lines([row.get("value") for row in rows])
    base, changed, _, _ = _from_lines(values)
    declared = value.get("hexagrams")
    if not isinstance(declared, dict):
        raise OracleError("iching_result has no declared base and changed hexagrams")
    for key, number in (("base",base),("changed",changed)):
        if not isinstance(declared.get(key),dict) or type(declared[key].get("number")) is not int or declared[key]["number"] != number:
            raise OracleError("iching_result hexagrams disagree with the actual six line values")
    return values, hashlib.sha256(_canonical(value)).hexdigest()


def _yilin(params, method, output):
    data, index = _load("yilin")
    values, record = None, {"source": "user_supplied_pair", "physical_cast_observed": False}
    if method == "pair":
        if "base" not in params or "changed" not in params:
            return {**output, "status": "needs_input", "required": ["base", "changed"]}
        base = _integer(params["base"],1,64,"base")
        changed = _integer(params["changed"],1,64,"changed")
        # Lookup has no implied line path; a pair alone does not reveal a physical casting procedure.
        base_bits, changed_bits = _number_bits(base), _number_bits(changed)
    elif method == "lines":
        if "lines" not in params:
            return {**output, "status": "needs_input", "required": ["lines"]}
        values = _six_lines(params["lines"])
        base, changed, base_bits, changed_bits = _from_lines(values)
        record = {"source": "user_supplied_line_values", "line_order": "bottom-to-top", "physical_cast_observed": False}
    elif method == "iching":
        if "iching_result" not in params:
            return {**output, "status": "needs_input", "required": ["iching_result"]}
        values, source_hash = _iching_input(params["iching_result"])
        base, changed, base_bits, changed_bits = _from_lines(values)
        record = {"source": "supplied_iching_result_verified_from_lines", "source_result_sha256": source_hash,
                  "line_order": "bottom-to-top", "physical_cast_observed": False}
    else:
        bits, record = _sample_bits("yilin",params.get("seed"),18)
        groups = [bits[i:i+3] for i in range(0,18,3)]
        values = [6+sum(group) for group in groups]
        record.update(coin_groups_bottom_to_top=groups, coin_weight="each coin contributes 2 or 3; line=6+number_of_3_faces")
        base, changed, base_bits, changed_bits = _from_lines(values)
    names = {row["number"]:row["name"] for row in data["hexagrams"]}
    entry = copy.deepcopy(index[(base,changed)])
    output.update(status="calculated", hexagrams={"base":{"number":base,"name":names[base],"lines_bottom_to_top":base_bits},
                                                 "changed":{"number":changed,"name":names[changed],"lines_bottom_to_top":changed_bits}},
                  line_values_bottom_to_top=values, cast_record=record,
                  oracle={"key":f"{base}:{changed}","label":names[base]+"之"+names[changed],**entry})
    if values is not None:
        output["moving_positions"] = [i+1 for i,v in enumerate(values) if v in (6,9)]
    output["rules"].update(selection="按本卦林、之卦条查原文；不变卦查同卦条", line_values="6老阴变阳、7少阳、8少阴、9老阳变阴",
                            pair_does_not_imply_casting_method=True)
    return output


def _piece_rows(pieces):
    if not isinstance(pieces,dict) or set(pieces) != {"upper","middle","lower"}:
        raise OracleError("pieces must contain exactly upper, middle and lower arrays")
    rows=[]
    for layer in ("upper","middle","lower"):
        row=pieces[layer]
        if not isinstance(row,list) or len(row)!=4 or any(type(bit) is not int or bit not in (0,1) for bit in row):
            raise OracleError("Each layer requires four integer 0/1 faces (1=inscribed side up)")
        rows.append(list(row))
    return rows


def _lingqijing(params, method, output):
    _,index=_load("lingqijing")
    rows=None
    record={"source":"user_supplied_counts","physical_cast_observed":False}
    if method=="counts":
        if "counts" not in params:
            return {**output,"status":"needs_input","required":["counts"]}
        counts=params["counts"]
        if not isinstance(counts,list) or len(counts)!=3:
            raise OracleError("counts must contain upper/middle/lower counts")
        counts=[_integer(value,0,4,"count") for value in counts]
    elif method=="pieces":
        if "pieces" not in params:
            return {**output,"status":"needs_input","required":["pieces"]}
        rows=_piece_rows(params["pieces"])
        counts=[sum(row) for row in rows]
        record={"source":"user_supplied_twelve_faces","physical_cast_observed":False}
    else:
        bits,record=_sample_bits("lingqijing",params.get("seed"),12)
        rows=[bits[0:4],bits[4:8],bits[8:12]]
        counts=[sum(row) for row in rows]
        record.update(piece_order="upper4,middle4,lower4; 1=inscribed face up, 0=blank",
                      elementary_outcomes=4096, count_shape_multiplicity=math.prod(math.comb(4,n) for n in counts),
                      note="棋形概率按十二枚独立公平正反模型计算，125种计数棋形并非等概率；不代表占验概率。")
    entry=copy.deepcopy(index[tuple(counts)])
    display_rows=rows if rows is not None else [[1]*n+[0]*(4-n) for n in counts]
    output.update(status="calculated", cast_record=record,
                  figure={"number":entry["number"],"name":entry["name"],"counts":counts,"image":entry["image"],
                          "display_is_count_layout":rows is None,
                          "rows":[{"layer":layer,"label":label,"marked":n,"blank":4-n,"faces":faces}
                                  for layer,label,n,faces in zip(("upper","middle","lower"),("上","中","下"),counts,display_rows)]},
                  oracle={"key":":".join(map(str,counts)),**entry})
    output["rules"].update(selection="上、中、下各四枚，有字面向上分别计0..4；计数三元组查辞",
                            zero_case="0,0,0对应纯阴镘，原版另列124卦之外；本数据查询号125，不自动重掷",
                            count_layout_is_not_physical_piece_position=rows is None)
    return output


def calculate(system, params:dict):
    """Calculate only an explicitly supplied/selected casting form and read its original text."""
    if not isinstance(system,str) or system not in DATA_HASHES:
        raise OracleError("system must be yilin or lingqijing")
    method,question=_params(system,params)
    data,_=_load(system)
    echoed=copy.deepcopy(params)
    if "iching_result" in echoed:
        echoed["iching_result"]={"sha256":hashlib.sha256(_canonical(params["iching_result"])).hexdigest(),"system":"iching"}
    echoed.update(method=method,question=question)
    output={"schema_version":1,"system":system,"status":"needs_input","input":echoed,
            "rules":{"edition":data["edition"],"entry_count":len(data["entries"]),"data_sha256":DATA_HASHES[system],
                     "text_type":"primary_classical_text; ancient commentary and editorial notes are separately labeled"},
            "limitations":list(_LIMITS)}
    return _yilin(params,method,output) if system=="yilin" else _lingqijing(params,method,output)


def _json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:
                raise OracleError("Duplicate JSON key: "+key)
            result[key]=value
        return result
    return json.loads(text,object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in ()).throw(OracleError("Nonfinite JSON constant")))


class Parser(argparse.ArgumentParser):
    def error(self,message):
        raise OracleError(message)


def main(argv=None):
    parser=Parser(description=__doc__,allow_abbrev=False)
    parser.add_argument("system",nargs="?",choices=tuple(DATA_HASHES))
    parser.add_argument("--params",help="explicit JSON object string; no automatic file or network read")
    parser.add_argument("--probe",action="store_true")
    try:
        args=parser.parse_args(argv)
        if args.probe:
            if args.system or args.params is not None:
                raise OracleError("--probe does not accept a system or params")
            value=probe()
        else:
            if args.system is None:
                raise OracleError("Specify yilin or lingqijing")
            value=calculate(args.system,_json(args.params) if args.params is not None else {})
        print(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))
        return 0 if value["status"] != "needs_input" else 2
    except (ValueError,TypeError,OSError,RecursionError) as exc:
        print(json.dumps({"schema_version":1,"system":getattr(locals().get("args"),"system",None),"status":"invalid_input",
                          "error":{"code":"classic_oracle_input","message":str(exc)}},ensure_ascii=False))
        return 2


if __name__=="__main__":
    sys.exit(main())
