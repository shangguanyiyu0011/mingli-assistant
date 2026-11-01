"""Authenticated, loopback-only visual workbench. Uses Python standard library."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
import mimetypes
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

sys.dont_write_bytecode = True
from workbench_catalog import VERSION, catalog
from output_paths import guard_output

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"[a-f0-9]{32}")
MAX_BODY = 65536
MAX_RECORD = 12_000_000


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("重复的 JSON 字段。")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("JSON 不接受非有限数值。")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def record_digest(record):
    content = {k:v for k,v in record.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def check_record(record):
    from fortune import compatible_system
    if not isinstance(record, dict) or record.get("record_schema") != 1:
        raise ValueError("历史记录缺少受支持的版本和校验信息。")
    system = record.get("system")
    if system not in {s["id"] for s in catalog()["systems"]}:
        raise ValueError("历史记录的方法无效。")
    result = record.get("result")
    if not isinstance(result, dict) or not compatible_system(result.get("system"), system):
        raise ValueError("历史记录的方法与计算结果不一致。")
    if not isinstance(record.get("params"), dict) or not isinstance(record.get("view"), dict):
        raise ValueError("历史记录缺少输入或盘面。")
    if not isinstance(record.get("sha256"), str) or not secrets.compare_digest(record["sha256"], record_digest(record)):
        raise ValueError("历史记录校验失败，内容已变化。")
    return record


class Records:
    def __init__(self, directory, *, agent_mode=False):
        supplied = Path(directory).expanduser()
        if not supplied.is_absolute():
            raise ValueError("工作台资料目录必须为绝对路径。")
        if agent_mode:
            from agent_intake import guard_data_directory
            self.root = guard_data_directory(supplied)
        else:
            self.root = guard_output(supplied)
        if self.root == Path(self.root.anchor):
            raise ValueError("资料目录不能为磁盘根目录。")
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def save(self, value):
        record = {**value, "id": secrets.token_hex(16), "created_at": datetime.now(timezone.utc).isoformat(), "record_schema": 1, "version": VERSION}
        record["sha256"] = record_digest(record)
        check_record(record)
        raw = json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_RECORD:
            raise ValueError("本次记录过大，未写入历史。")
        with self.lock:
            target = self.root / (record["id"] + ".json")
            fd, temp = tempfile.mkstemp(prefix=".writing-", dir=self.root)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                if target.exists():
                    raise ValueError("记录标识冲突。")
                os.replace(temp, target)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        return record

    def read(self, id_):
        if not ID.fullmatch(id_):
            raise ValueError("记录标识无效。")
        path = self.root / (id_ + ".json")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD:
            raise FileNotFoundError("记录不存在。")
        result = strict_json(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or result.get("id") != id_:
            raise ValueError("历史记录校验失败。")
        return check_record(result)

    def list(self):
        paths = sorted((p for p in self.root.glob("*.json") if ID.fullmatch(p.stem)),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:200]
        rows = []
        for path in paths:
            try:
                r = self.read(path.stem)
                rows.append({k: r[k] for k in ("id", "system", "name", "created_at")} | {
                    "title": str(r.get("params", {}).get("question", ""))[:80]})
            except (ValueError, OSError, KeyError):
                continue
        return {"items": rows}


def worker(request, *, timeout=None, cancel_event=None):
    command=[sys.executable, "-X", "utf8", "-B", str(ROOT / "scripts/workbench_api.py")]
    budget=timeout if timeout is not None else 600 if request.get("operation") in ("prepare", "submit") else 180
    payload=json.dumps(request, ensure_ascii=False, allow_nan=False)
    if request.get("operation")=="collect":
        child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
        deadline=time.monotonic()+budget
        first=True
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set() or time.monotonic()>=deadline:
                    raise subprocess.TimeoutExpired(command,budget)
                try:
                    stdout,_=child.communicate(input=payload if first else None,timeout=min(0.2,max(0.001,deadline-time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    first=False
        except BaseException:
            child.kill()  # Only the collector child started above, never another service/process.
            child.communicate()
            raise
        response_stdout=stdout
    else:
        child = subprocess.run(command,input=payload,text=True,encoding="utf-8",capture_output=True,timeout=budget)
        response_stdout=child.stdout
    if len(response_stdout) > MAX_RECORD:
        raise ValueError("计算结果超过本地工作台限制。")
    try:
        response = strict_json(response_stdout)
    except ValueError as exc:
        raise ValueError("计算工具没有返回有效结果，请检查所需引擎状态。") from exc
    if not response.get("ok"):
        raise ValueError(str(response.get("error", {}).get("message", "计算失败。")))
    return response["value"]


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, records, *, agent_mode=False):
        if address[0] != "127.0.0.1":
            raise ValueError("本机资料服务只允许 127.0.0.1。")
        super().__init__(address, Handler)
        self.agent_mode = agent_mode
        self.token = secrets.token_urlsafe(32)
        self.records = records
        self.reports_root = guard_output(records.root / "reports")
        self.slots = threading.BoundedSemaphore(2)
        self.base = f"http://127.0.0.1:{self.server_port}"
        self.submission_lock = threading.Lock()
        self.submission_event = threading.Event()
        self.submission_payload = None
        self.submission_state = "collecting"
        self.collection_cancel = threading.Event()
        self.collection_deadline = None
        from photo_uploads import PhotoSession
        self.photos = PhotoSession(records.root / ".photo-sessions")
        self.pending_collection = None
        self.collection_committed = False

    def server_close(self):
        try:
            if hasattr(self,"photos"):
                self.photos.cleanup()
            if getattr(self,"pending_collection",None) is not None and not self.collection_committed:
                from photo_uploads import discard_reserved
                discard_reserved(self.pending_collection,self.photos.id)
        except (OSError,ValueError):
            pass  # Never broaden cleanup if a private path changed ownership.
        finally:
            super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "MingliLocal/5"

    def log_message(self, *args):
        pass  # Birth inputs, tokens and record IDs are never request-logged.

    def respond(self, code, value, mime="application/json; charset=utf-8", *, standalone=False, session=False):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8") if mime.startswith("application/json") else value
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'" if standalone else "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if session:
            self.send_header("Set-Cookie", "mingli_session=" + self.server.token + "; HttpOnly; SameSite=Strict; Path=/")
        try:
            self.end_headers()
            self.wfile.write(raw)
            self.wfile.flush()
            return True
        except OSError:
            return False

    def error(self, code, message):
        self.respond(code, {"error": {"code": str(code), "message": message}})

    def trusted(self, auth=False, allow_cookie=False):
        if self.headers.get("Host") != urlsplit(self.server.base).netloc:
            self.error(403, "仅接受本机工作台地址。")
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.base:
            self.error(403, "请求来源与工作台不一致。")
            return False
        authenticated = secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.token)
        if allow_cookie and not authenticated:
            try:
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                entry = cookies.get("mingli_session")
                authenticated = bool(entry and secrets.compare_digest(entry.value, self.server.token))
            except Exception:
                authenticated = False
        if auth and not authenticated:
            self.error(401, "本次页面会话已失效，请重新打开工作台。")
            return False
        return True

    def do_GET(self):
        if not self.trusted():
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            if path.startswith("/files/"):
                if not self.trusted(auth=True, allow_cookie=True):
                    return
                match = re.fullmatch(r"/files/([a-f0-9]{32})/(personal-a\.html|personal-b\.html|pair\.html)", path)
                if not match:
                    return self.error(404, "没有此报告文件。")
                job = self.server.reports_root / match[1]
                target = job / match[2]
                if job.is_symlink() or target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(self.server.reports_root.resolve()) or target.stat().st_size > 30_000_000:
                    return self.error(404, "报告不存在。")
                return self.respond(200, target.read_bytes(), "text/html; charset=utf-8", standalone=True)
            if path == "/api/catalog":
                return self.respond(200, catalog())
            if path == "/api/photos" or path.startswith("/api/photos/"):
                if not self.trusted(auth=True,allow_cookie=path!="/api/photos"):
                    return
                if self.server.submission_state!="collecting" or self.server.collection_cancel.is_set() or self.server.collection_deadline and time.monotonic()>=self.server.collection_deadline:
                    return self.error(410,"本次照片会话已经结束。")
                from photo_uploads import PhotoError
                try:
                    if path=="/api/photos":
                        return self.respond(200,self.server.photos.list())
                    id_=path.removeprefix("/api/photos/")
                    if not ID.fullmatch(id_):
                        return self.error(404,"没有此照片。")
                    data,mime=self.server.photos.preview(id_)
                    return self.respond(200,data,mime)
                except PhotoError as exc:
                    return self.error(404,str(exc))
                except OSError:
                    return self.error(400,"照片本地读取失败。")
            if path.startswith("/api/"):
                if not self.trusted(auth=True):
                    return
                if path == "/api/history":
                    return self.respond(200, self.server.records.list())
                if path.startswith("/api/history/"):
                    return self.respond(200, self.server.records.read(path.removeprefix("/api/history/")))
                if path == "/api/reference":
                    from fortune import find_system
                    name = parse_qs(parsed.query).get("id", [""])[0]
                    ref = ROOT / find_system(name)["reference"]
                    return self.respond(200, {"text": ref.read_text(encoding="utf-8")})
                return self.error(404, "没有此接口。")
            from reader_art import KEYS as ART_KEYS
            if path in {'/art/'+key+'.png' for key in ART_KEYS}:
                source=ROOT/'assets/art'/path.rsplit('/',1)[-1]
                return self.respond(200,source.read_bytes(),'image/png')
            files = {"/": "intake.html", "/intake": "intake.html", "/intake.html": "intake.html", "/workbench": "index.html", "/index.html": "intake.html", "/app.css": "app.css", "/app.js": "app.js", "/renderer.js": "renderer.js", "/intake.css": "intake.css", "/intake.js": "intake.js", "/report.css": "report.css", "/report.js": "report.js"}
            files.update({"/intake-draws.js":"intake-draws.js","/intake-draws.css":"intake-draws.css","/art-assets.js":"art-assets.js","/i18n.js":"i18n.js"})
            if path not in files:
                return self.error(404, "没有此文件。")
            source = ROOT / "ui" / files[path]
            raw = source.read_bytes()
            if files[path]=="intake.html":
                from offline_intake import inline_locales
                raw=inline_locales(raw.decode("utf-8-sig")).encode("utf-8")
            if source.suffix == ".html":
                mode = '<meta name="mingli-intake-mode" content="agent">' if self.server.agent_mode else ""
                raw = raw.replace(b"<head>", ("<head>" + mode + "<meta name=\"workbench-token\" content=\"" + self.server.token + "\">").encode("ascii"), 1)
            mime = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}[source.suffix]
            self.respond(200, raw, mime, session=source.suffix == ".html")
        except FileNotFoundError:
            self.error(404, "记录或页面不存在。")
        except (ValueError, OSError) as exc:
            self.error(400, str(exc))

    def discard_rejected_body(self):
        # Drain only a bounded declared body, so Windows does not reset before
        # the already-written 401/403 can reach a legitimate local client.
        old=self.connection.gettimeout()
        try:
            from photo_uploads import MAX_UPLOAD_BODY
            length=int(self.headers.get("Content-Length","0"))
            if 0<length<=MAX_UPLOAD_BODY and not self.headers.get("Transfer-Encoding"):
                self.connection.settimeout(0.2)
                self.rfile.read(length)
        except (ValueError,OSError):
            pass
        finally:
            self.connection.settimeout(old)

    def do_POST(self):
        if not self.trusted(auth=True):
            self.discard_rejected_body()
            return
        if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
            return self.error(415, "仅接受有长度的 JSON 请求。")
        try:
            path = urlsplit(self.path).path
            from photo_uploads import MAX_UPLOAD_BODY
            limit=MAX_UPLOAD_BODY if path=="/api/photos" else 256000 if self.server.agent_mode or path=="/api/submit" else MAX_BODY
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= limit:
                return self.error(413, "请求过大或为空。")
            request = strict_json(self.rfile.read(length).decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("请求必须是参数对象。")
            if path in ("/api/photos","/api/photos/remove"):
                return self.photo_action(request,remove=path.endswith("/remove"))
            if self.server.agent_mode:
                if path not in ("/api/submit", "/api/cancel"):
                    return self.error(403, "一次性收集不提供计算或引擎准备。")
                return self.collect(request, cancel=path=="/api/cancel")
            if path not in ("/api/calculate", "/api/prepare", "/api/submit"):
                return self.error(404, "没有此接口。")
            allowed = {"mode", "people", "preferences", "method_options"} if path.endswith("submit") else {"system", "params"} if path.endswith("calculate") else {"system"}
            if set(request) - allowed or (not path.endswith("submit") and request.get("system") not in {s["id"] for s in catalog()["systems"]}):
                raise ValueError("方法或参数无效。")
            if not self.server.slots.acquire(blocking=False):
                return self.error(429, "有计算正在进行，请稍后重试。")
            try:
                request["operation"] = "submit" if path.endswith("submit") else "prepare" if path.endswith("prepare") else "calculate"
                photo_lock=False
                if request["operation"] == "submit":
                    if not self.server.submission_lock.acquire(blocking=False):
                        return self.error(409,"本次资料正在接收。")
                    photo_lock=True
                try:
                    if request["operation"]=="submit":
                        from intake_flow import normalize_request
                        native=normalize_request({k:v for k,v in request.items() if k!="operation"},allow_unresolved_places=True)
                        snapshot=self.server.photos.snapshot(native)
                        request["reports_dir"] = str(self.server.reports_root)
                        if snapshot:
                            request["photo_manifest"]=str(snapshot)
                    value = worker(request)
                    if request["operation"]=="submit" and value.get("status") in ("ready","partial"):
                        self.server.photos.cleanup()
                        from photo_uploads import PhotoSession
                        self.server.photos=PhotoSession(self.server.records.root/".photo-sessions")
                finally:
                    if photo_lock:
                        self.server.submission_lock.release()
                if request["operation"] == "calculate":
                    value = self.server.records.save(value)
                self.respond(200, value)
            finally:
                self.server.slots.release()
        except subprocess.TimeoutExpired:
            self.error(504, "本次计算超时，未生成历史记录。")
        except (ValueError, OSError, UnicodeError, RecursionError) as exc:
            self.error(400, str(exc))

    def photo_action(self,request,*,remove=False):
        if not self.server.submission_lock.acquire(blocking=False):
            return self.error(409,"本次资料正在接收，暂不能修改照片。")
        try:
            if self.server.submission_state!="collecting" or self.server.collection_cancel.is_set() or self.server.collection_deadline and time.monotonic()>=self.server.collection_deadline:
                return self.error(410,"本次照片会话已经结束。")
            from photo_uploads import PhotoError
            try:
                if remove:
                    if set(request)!={"id"}:
                        raise PhotoError("撤回只接受本会话照片id。")
                    value=self.server.photos.remove(request["id"])
                else:
                    value=self.server.photos.upload(request)
                return self.respond(200,value)
            except PhotoError as exc:
                return self.error(400,str(exc))
            except (OSError,TypeError,UnicodeError):
                return self.error(400,"照片本地校验未通过，请重新选择JPG/PNG。")
        finally:
            self.server.submission_lock.release()

    def collect(self, request, *, cancel=False):
        if not self.server.submission_lock.acquire(blocking=False):
            return self.error(409, "本次资料正在接收或已经提交，不能重复覆盖。")
        try:
            if self.server.submission_state!="collecting":
                return self.error(409, "本次资料已提交或已取消，不能重复覆盖。")
            if self.server.token in json.dumps(request,ensure_ascii=False,allow_nan=False):
                return self.error(400, "填写资料不能包含本次会话凭据。")
            if cancel:
                if request:
                    return self.error(400, "取消操作不接受填写资料。")
                value={"status":"cancelled","job_id":None,"files":[],"questions":[],"warnings":["本次收集已取消，未将资料视为已提交。"]}
            else:
                from intake_flow import normalize_request,IntakeError,MissingBasics
                from photo_uploads import reserve_collection,discard_reserved,PhotoError
                try:
                    native=normalize_request(request,allow_unresolved_places=True)
                    snapshot=self.server.photos.snapshot(native)
                except (IntakeError,PhotoError) as exc:
                    return self.respond(400,{"status":"needs_input" if isinstance(exc,MissingBasics) else "invalid_input","job_id":None,"files":[],"questions":[],"warnings":[str(exc)]})
                remaining=self.server.collection_deadline-time.monotonic() if self.server.collection_deadline else None
                if remaining is not None and remaining<=0:
                    return self.error(410,"本次收集已经结束。")
                reserved=reserve_collection(self.server.records.root/"collected",self.server.photos.id)
                self.server.pending_collection=reserved
                operation={"operation":"collect","data_dir":str(self.server.records.root/"collected"),"request":request,
                           "reserved_job":str(reserved),"reservation_owner":self.server.photos.id}
                if snapshot:
                    operation["photo_session"]=str(snapshot)
                try:
                    value=worker(operation,timeout=remaining,cancel_event=self.server.collection_cancel)
                except BaseException:
                    discard_reserved(reserved,self.server.photos.id)
                    self.server.pending_collection=None
                    raise
                if value.get("status")!="submitted":
                    discard_reserved(reserved,self.server.photos.id)
                    self.server.pending_collection=None
                if self.server.collection_cancel.is_set():
                    return self.error(410,"本次收集已经结束，未标记为完成。")
                if value.get("status")!="submitted":
                    return self.respond(400,{k:v for k,v in value.items() if k not in {"request_file","photo_manifest"}})
            # Only a successful response flush releases the CLI's submission wait.
            self.server.submission_state=value["status"]
            public={key:item for key,item in value.items() if key not in {"request_file","photo_manifest"}}
            delivered=self.respond(200,public)
            self.server.collection_committed=bool(delivered and value["status"]=="submitted")
            self.server.photos.cleanup()
            self.server.submission_payload=value if delivered else {
                "status":"error","job_id":value.get("job_id"),"files":[],"questions":[],
                "warnings":["资料响应未能送达，本次收集未标记为完成。"]}
            self.server.submission_event.set()
        finally:
            self.server.submission_lock.release()


def default_data_directory():
    override = os.environ.get("MINGXUE_WORKBENCH_DATA")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "mingxue/workbench"
    return Path.home() / ".local/share/mingxue/workbench"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--port", type=int, default=0, help="0 chooses a free loopback port")
    parser.add_argument("--data-dir", help="external absolute records directory")
    parser.add_argument("--open", action="store_true", help="open the local workbench in the default browser")
    parser.add_argument("--ready-file", help="explicit external JSON readiness file; contains no session token")
    parser.add_argument("--agent", "--once", dest="agent_mode", action="store_true", help="collect one validated native request without calculation, then exit")
    parser.add_argument("--timeout", type=float, default=900, help="agent/once collection timeout in seconds")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("invalid port")
    if args.agent_mode:
        if not args.data_dir or not math.isfinite(args.timeout) or not 0 < args.timeout <= 86400:
            parser.error("agent mode requires explicit --data-dir and timeout in (0,86400]")
        return run_once(args)
    server = Server(("127.0.0.1", args.port), Records(args.data_dir or default_data_directory()))
    ready = {"status": "ready", "version": VERSION, "url": server.base, "data_directory": str(server.records.root), "network_scope": "loopback_only"}
    if args.ready_file:
        target = guard_output(args.ready_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(ready, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(ready, ensure_ascii=False), flush=True)
    if args.open:
        webbrowser.open(server.base)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def run_once(args):
    from agent_intake import guard_data_directory
    server=None
    thread=None
    try:
        directory=guard_data_directory(args.data_dir)
        ready_path=None
        if args.ready_file:
            candidate=Path(args.ready_file).expanduser()
            if not candidate.is_absolute():
                raise ValueError("就绪文件须为新的外置绝对路径。")
            ready_path=guard_output(candidate)
            if ready_path.exists():
                raise ValueError("就绪文件已存在，请指定新文件以保留原件。")
        server=Server(("127.0.0.1",args.port),Records(directory,agent_mode=True),agent_mode=True)
        ready={"status":"collecting","mode":"agent","version":VERSION,"url":server.base,
               "network_scope":"loopback_only","timeout_seconds":args.timeout}
        if ready_path:
            ready_path.parent.mkdir(parents=True,exist_ok=True)
            with ready_path.open("x",encoding="utf-8") as stream:
                json.dump(ready,stream,ensure_ascii=False,allow_nan=False)
        thread=threading.Thread(target=server.serve_forever,kwargs={"poll_interval":0.05},daemon=True)
        server.collection_deadline=time.monotonic()+args.timeout
        thread.start()
        print(json.dumps(ready,ensure_ascii=False),flush=True)
        if args.open:
            webbrowser.open(server.base)
        complete=server.submission_event.wait(args.timeout)
        if complete:
            result=server.submission_payload
        else:
            result={"status":"timeout","job_id":None,"files":[],"questions":[],"warnings":["等待有效提交超时；没有取得已完成资料。"]}
        status=result["status"]
        exit_code=0 if status=="submitted" else 3 if status=="timeout" else 130 if status=="cancelled" else 1
    except KeyboardInterrupt:
        result={"status":"cancelled","job_id":None,"files":[],"questions":[],"warnings":["本次收集已取消，未将资料视为已提交。"]}
        exit_code=130
    except (ValueError,OSError,RuntimeError):
        result={"status":"error","job_id":None,"files":[],"questions":[],"warnings":["一次性本地收集未能启动或完成；请检查外置目录及可用端口。"]}
        exit_code=1
    finally:
        if server is not None:
            server.collection_cancel.set()
            server.token=secrets.token_urlsafe(32)
            server.submission_state="closed"
            if thread is not None and thread.is_alive():
                server.shutdown()
                thread.join(timeout=2)
                if server.submission_lock.acquire(timeout=2):
                    server.submission_lock.release()
            server.server_close()
    print(json.dumps(result,ensure_ascii=False,allow_nan=False),flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
