#!/usr/bin/env python3
"""搜书：标准库实现的独立搜索和下载 CLI（Python 3.10+）。

默认使用 Internet Archive 公开馆藏 API，兼容 LibGen 和显式启用的可选认证源；Anna's Archive 仅提供人工
搜索链接，不声称已自动检索。搜索和下载分开执行，stdout 始终输出单个
JSON 对象。缓存和网络下载临时文件写入 --work-dir / BOOK_SEARCH_WORK_DIR，
默认使用系统临时目录；凭据仅从环境读取，不写入会话，不读取浏览器数据。
条目收录、公开文件及来源权利元数据分别呈现，不将收录等同于授权核验。
"""

from __future__ import annotations

import argparse
import codecs
from datetime import datetime, timezone
from email.message import Message
from email.utils import collapse_rfc2231_value, parsedate_to_datetime
import errno
import hashlib
import html
from html.parser import HTMLParser
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import sys

sys.dont_write_bytecode = True

import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


LIBGEN = "https://libgen.li"
ANNAS_SEARCH = "https://annas-archive.org/search"
ZLIB_HOSTS = ("https://z-library.sk", "https://z-lib.id", "https://zlib.id")
ARCHIVE = "https://archive.org"
USER_AGENT = "MingxueBookSearch/3.0"
MAX_METADATA_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
SUPPORTED_FORMATS = frozenset(
    {"pdf", "epub", "djvu", "mobi", "azw", "azw3", "txt", "fb2", "docx", "zip", "cbz", "rar", "cbr"}
)
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
SKILL_ROOT = Path(__file__).resolve().parents[1]


class BookError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, retry_after=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after

    def as_dict(self):
        result = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            result["retry_after_seconds"] = self.retry_after
        return result


def _now():
    return datetime.now(timezone.utc).isoformat()


def _retry_after(raw):
    if not raw:
        return None
    try:
        seconds = float(raw)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except (ValueError, TypeError):
        try:
            due = parsedate_to_datetime(raw)
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            return max(0.0, (due - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


def _path_forms(value):
    """同时保留字面范围及真实范围，覆盖现有符号链接和 Windows junction。"""
    expanded = Path(value).expanduser()
    lexical = Path(os.path.abspath(expanded))
    return lexical, expanded.resolve()


def _validate_user_path(value, purpose="用户目录"):
    lexical, resolved = _path_forms(value)
    protected = [SKILL_ROOT, Path(tempfile.gettempdir()) / "mingxue-master-cache"]
    protected.extend(
        Path(os.environ[key]) for key in ("MINGXUE_CACHE_DIR", "MINGXUE_RESOURCE_DIR") if os.environ.get(key)
    )
    from output_paths import protected_output_roots
    protected.extend(protected_output_roots())
    protected_forms = [form for root in protected for form in _path_forms(root)]
    if any(candidate.is_relative_to(root) for candidate in (lexical, resolved) for root in protected_forms):
        raise BookError("protected_path", f"{purpose}必须位于技能源码、资源树及资源缓存之外。")
    # 也识别从其他解压位置或旧安装保留的已知资源缓存目录。
    for candidate in (lexical, resolved):
        if any(
            parent.name.casefold() == "mingxue-master-cache" or parent.name.casefold().startswith("mingxue-resources-")
            for parent in (candidate, *candidate.parents)
        ):
            raise BookError("protected_path", f"{purpose}不得位于打包资源缓存。")
    return resolved


def _validate_url(url: str, *, allow_http: bool = False) -> str:
    parsed = urllib.parse.urlsplit(url)
    allowed = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in allowed or not parsed.hostname or parsed.username or parsed.password:
        raise BookError("unsafe_url", "请求地址必须为不含账号密码的 HTTPS 地址。")
    return url


def _require_archive_identity(url, agent_model):
    host = urllib.parse.urlsplit(url).hostname or ""
    if (host == "archive.org" or host.endswith(".archive.org")) and (
        not agent_model or agent_model.strip().lower() in {"unspecified", "unknown", "none"}
    ):
        raise BookError("model_id_required", "archive 的 AI 请求需要实际模型名；请显式传 --agent-model 或设置 BOOK_SEARCH_AGENT_MODEL。")


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁止 HTTPS 降级，并阻止认证头经跨站重定向泄漏。"""

    def __init__(self, agent_model=None):
        super().__init__()
        self.agent_model = agent_model

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        _require_archive_identity(newurl, self.agent_model)
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        sensitive = {"authorization", "cookie", "remix-userid", "remix-userkey"}
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            if any(key.lower() in sensitive for key, _ in req.header_items()):
                raise BookError("auth_redirect", "认证接口跨站重定向已拒绝。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    def __init__(self, timeout=30.0, retries=1, *, opener=None, sleep=time.sleep, allow_http=False, agent_model=None):
        if not 1 <= timeout <= 120:
            raise BookError("invalid_arguments", "--timeout 必须在 1 到 120 秒之间。")
        if not 0 <= retries <= 3:
            raise BookError("invalid_arguments", "--retries 必须在 0 到 3 之间。")
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep
        self.allow_http = allow_http
        self.agent_model = agent_model if agent_model is not None else os.environ.get("BOOK_SEARCH_AGENT_MODEL")
        self.agent_model = self.agent_model.strip() if self.agent_model else None
        if self.agent_model and not re.fullmatch(r"[A-Za-z0-9_.:/ -]{1,100}", self.agent_model):
            raise BookError("invalid_arguments", "--agent-model 仅允许 1–100 个模型名称字符。")
        self.user_agent = f"{USER_AGENT} ({self.agent_model or 'model unspecified'}; Python urllib)"
        # Local/manual operations and early identity checks do not need a TLS
        # context. Construct it only when actually opening a network request.
        self._ssl_context = None
        self._opener = opener

    @property
    def ssl_context(self):
        if self._ssl_context is None:
            try:
                # Certificate and hostname checks stay enabled.
                self._ssl_context = ssl.create_default_context()
            except (OSError, ValueError) as exc:
                raise BookError("tls_setup_error", "本地 TLS 环境无法初始化；请检查系统证书及运行环境。") from exc
        return self._ssl_context

    @property
    def opener(self):
        if self._opener is None:
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=self.ssl_context), SafeRedirectHandler(self.agent_model))
        return self._opener

    @opener.setter
    def opener(self, value):
        self._opener = value

    def open_once(self, url, *, headers=None, data=None):
        _validate_url(url, allow_http=self.allow_http)
        _require_archive_identity(url, self.agent_model)
        request_headers = {"User-Agent": self.user_agent}
        request_headers.update(headers or {})
        req = urllib.request.Request(url, headers=request_headers, data=data)
        try:
            response = self.opener.open(req, timeout=self.timeout)
            try:
                _validate_url(response.geturl(), allow_http=self.allow_http)
            except BookError:
                response.close()
                raise
            return response
        except urllib.error.HTTPError as exc:
            delay = _retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            status = exc.code
            exc.close()
            if status == 429:
                delay = 30.0 if delay is None else delay
                raise BookError(
                    "rate_limited", "源站限流；按 Retry-After 等待，超过 60 秒则停止本次请求。",
                    retryable=delay <= 60, retry_after=delay,
                ) from None
            raise BookError(
                "http_error", f"源站返回 HTTP {status}。", retryable=status in RETRY_STATUSES and (delay is None or delay <= 60),
                retry_after=delay,
            ) from None
        except ssl.SSLCertVerificationError:
            raise BookError("tls_error", "TLS 证书或主机名校验失败。") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise BookError("tls_error", "TLS 证书或主机名校验失败。") from None
            raise BookError("network_error", "网络连接失败或超时。", retryable=True) from None
        except (socket.timeout, TimeoutError, ConnectionError, OSError):
            raise BookError("network_error", "网络连接失败或超时。", retryable=True) from None

    def run(self, operation):
        for attempt in range(self.retries + 1):
            try:
                return operation()
            except BookError as exc:
                if not exc.retryable or attempt == self.retries:
                    raise
                self.sleep(max(min(0.25 * (2 ** attempt), 2.0), exc.retry_after or 0))
        raise AssertionError("unreachable")

    def read_bytes(self, url, *, headers=None, data=None, limit=MAX_METADATA_BYTES):
        def attempt():
            try:
                with self.open_once(url, headers=headers, data=data) as response:
                    payload = response.read(limit + 1)
                    if len(payload) > limit:
                        raise BookError("response_too_large", "源站元数据超过大小限制。")
                    _check_content_length(response.headers, len(payload))
                    return payload
            except (http.client.HTTPException, OSError, EOFError):
                raise BookError("interrupted_response", "源站响应读取中断。", retryable=True) from None

        return self.run(attempt)

    def read_text(self, url, **kwargs):
        return self.read_bytes(url, **kwargs).decode("utf-8", "replace")

    def read_json(self, url, **kwargs):
        try:
            value = json.loads(self.read_text(url, **kwargs))
        except (json.JSONDecodeError, UnicodeError):
            raise BookError("invalid_response", "源站未返回有效 JSON。") from None
        if not isinstance(value, dict):
            raise BookError("invalid_response", "源站 JSON 结构无效。")
        return value


def _check_content_length(headers, actual):
    raw = headers.get("Content-Length")
    if raw is None:
        return
    try:
        expected = int(raw)
    except (TypeError, ValueError):
        raise BookError("invalid_response", "源站 Content-Length 无效。") from None
    if expected < 0 or actual != expected:
        raise BookError("incomplete_download", "收到的数据长度与源站声明不一致。", retryable=True)


class _TdParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells = []
        self._edition = False
        self._title = None
        self._plain = []

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self._edition = False
            self._title = None
            self._plain = []
        elif tag == "a" and dict(attrs).get("href", "").startswith("edition.php"):
            self._edition = True
            self._title = []

    def handle_endtag(self, tag):
        if tag == "a":
            self._edition = False
        elif tag == "td":
            self.cells.append(" ".join(self._title if self._title is not None else self._plain).strip())

    def handle_data(self, data):
        if self._edition and self._title is not None:
            self._title.append(data)
        else:
            self._plain.append(data)


def _extension(value):
    value = str(value or "").strip().lower().lstrip(".")
    return value if re.fullmatch(r"[a-z0-9]{1,10}", value) else ""


def _result_metadata(result):
    result["extension"] = _extension(result.get("extension"))
    supported = result["extension"] in SUPPORTED_FORMATS
    result["download"] = {"supported": supported}
    if not supported:
        result["download"]["reason"] = "未实现该格式的文件内容校验；请人工获取。"
    result.setdefault("edition", "")
    result.setdefault("edition_status", "not_stated")
    result.setdefault("available_formats", [result["extension"]] if result["extension"] else [])
    result.setdefault("acquisition_status", "download_not_checked" if supported else "unsupported_format")
    return result


def libgen_search(query, limit, client):
    fields = [
        ("req", query), ("columns[]", "title"), ("objects[]", "f"), ("topics[]", "l"),
        ("topics[]", "a"), ("res", str(limit)), ("files", "on"), ("gmode", "on"),
    ]
    data = client.read_text(f"{LIBGEN}/index.php?{urllib.parse.urlencode(fields)}")
    results = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", data, re.I | re.S):
        match = re.search(r"ads\.php\?md5=([a-f0-9]{32})", row, re.I)
        if not match:
            continue
        parser = _TdParser()
        parser.feed(row)
        cells = parser.cells
        if len(cells) < 8:
            continue
        results.append(_result_metadata({
            "source": "libgen", "md5": match.group(1).lower(),
            **dict(zip(("title", "author", "publisher", "year", "language", "pages", "size", "extension"),
                       [html.unescape(cell)[:500] for cell in cells[:8]])),
        }))
        if len(results) >= limit:
            break
    if not results and _is_interstitial(data):
        raise BookError("source_blocked", "源站返回验证、登录或错误页面，未得到搜索结果。")
    if not results and not re.search(
        r"no\s+(?:files?|books?|results?|records?)|nothing\s+found|0\s+(?:files?|books?|results?|records?)|"
        r"no\s+hits|没有(?:找到|结果)|未找到|(?:<th\b[^>]*>\s*Title\s*</th>.*<th\b[^>]*>\s*Author)",
        data, re.I | re.S,
    ):
        raise BookError("unrecognized_page", "源站页面结构无法识别，不能判定为无结果。")
    return results


def _is_interstitial(data):
    lowered = data[:100000].lower()
    return bool(re.search(
        r"(?:<title[^>]*>\s*(?:just a moment|access denied|error|attention required)|"
        r"cf-chl-|verify (?:that )?you are human|captcha|service unavailable|"
        r"<form[^>]*(?:login|sign[-_]?in)|name=[\"']password[\"'])", lowered
    ))


def _zlib_creds():
    userid = os.environ.get("Z_LIBRARY_ID", "").strip()
    userkey = os.environ.get("Z_LIBRARY_KEY", "").strip()
    if not userid or not userkey:
        raise BookError("credentials_missing", "显式使用 zlib 需要环境变量 Z_LIBRARY_ID 和 Z_LIBRARY_KEY。")
    if any(ch in userid + userkey for ch in "\r\n;"):
        raise BookError("invalid_credentials", "认证环境变量含不允许的控制字符或分隔符。")
    return {"remix-userid": userid, "remix-userkey": userkey}


def zlib_search(query, limit, client):
    credentials = _zlib_creds()
    fields = [("message", query), ("limit", str(limit))]
    fields.extend(("extensions[]", ext) for ext in ("pdf", "epub", "mobi", "djvu", "txt", "azw3"))
    payload_data = urllib.parse.urlencode(fields).encode()
    last_error = None
    for host in ZLIB_HOSTS:
        try:
            payload = client.read_json(
                f"{host}/eapi/book/search", data=payload_data,
                headers={**credentials, "Content-Type": "application/x-www-form-urlencoded"},
            )
            if not payload.get("success"):
                raise BookError("source_api_error", "认证源拒绝搜索或返回 API 错误。")
            books = payload.get("books")
            if not isinstance(books, list):
                raise BookError("invalid_response", "认证源搜索结果结构无效。")
            results = []
            for book in books[:limit]:
                if not isinstance(book, dict):
                    continue
                book_id, book_hash = str(book.get("id", "")), str(book.get("hash", ""))
                if not re.fullmatch(r"[0-9]+", book_id) or not re.fullmatch(r"[a-zA-Z0-9]{1,128}", book_hash):
                    continue
                results.append(_result_metadata({
                    "source": "zlib", "id": book_id, "hash": book_hash, "host": host,
                    **{key: str(book.get(key) or "")[:500]
                       for key in ("title", "author", "year", "extension", "language")},
                    "size": str(book.get("filesizeString") or "")[:100],
                }))
            if books and not results:
                raise BookError("invalid_response", "认证源返回的图书标识无法识别，不能判定为无结果。")
            return results
        except BookError as exc:
            last_error = exc
            # 认证和 API 拒绝不通过切换域名反复发送。
            if exc.code not in {"network_error", "http_error", "tls_error", "interrupted_response"}:
                raise
    raise last_error or BookError("source_unavailable", "认证源无法访问。")


def _metadata_text(value):
    if isinstance(value, list):
        return "; ".join(_metadata_text(part) for part in value)[:1000]
    return str(value or "")[:1000]


def _true(value):
    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def _archive_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value):
        raise BookError("invalid_response", "馆藏条目标识无效。")
    return value


def _archive_metadata(identifier, client):
    identifier = _archive_identifier(identifier)
    payload = client.read_json(f"{ARCHIVE}/metadata/{identifier}?extended_err=1")
    metadata = payload.get("metadata")
    if payload.get("error") or not isinstance(metadata, dict) or not isinstance(payload.get("files"), list):
        raise BookError("archive_item_unavailable", "馆藏条目元数据不可用或条目已移除。")
    if metadata.get("identifier", identifier) != identifier:
        raise BookError("invalid_response", "馆藏元数据与所选条目标识不一致。")
    return payload


def _archive_restricted(payload):
    metadata = payload.get("metadata", {})
    return any(_true(value) for value in (
        payload.get("is_dark"), payload.get("is_restricted"), payload.get("is_lendable"),
        metadata.get("access-restricted-item"),
    ))


def _archive_files(payload):
    if _archive_restricted(payload):
        return []
    candidates = []
    for entry in payload["files"]:
        if not isinstance(entry, dict) or _true(entry.get("private")):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name or len(name) > 1000 or "\\" in name or any(ord(char) < 32 for char in name):
            continue
        if name.startswith("/") or any(part in {"", ".", ".."} for part in name.split("/")):
            continue
        extension = _extension(Path(name).suffix)
        if extension not in SUPPORTED_FORMATS:
            continue
        try:
            size = int(entry.get("size", 0))
        except (ValueError, TypeError):
            continue
        if size <= 0:
            continue
        md5 = str(entry.get("md5") or "").lower()
        candidates.append({
            "name": name, "extension": extension, "format": _metadata_text(entry.get("format")),
            "size": size, "md5": md5 if re.fullmatch(r"[a-f0-9]{32}", md5) else "",
        })
    priority = {extension: index for index, extension in enumerate(("epub", "pdf", "txt", "djvu", "mobi", "azw3", "azw", "fb2", "docx", "zip", "cbz", "rar", "cbr"))}
    candidates.sort(key=lambda entry: (priority.get(entry["extension"], 99), entry["name"].count("/"), entry["name"]))
    return candidates[:100]


def _archive_result(document, client):
    identifier = _archive_identifier(document.get("identifier"))
    base = {
        "source": "archive", "id": identifier, "version_id": identifier,
        "title": _metadata_text(document.get("title")), "author": _metadata_text(document.get("creator")),
        "publisher": _metadata_text(document.get("publisher")), "year": _metadata_text(document.get("date")),
        "language": _metadata_text(document.get("language")), "edition": _metadata_text(document.get("edition")),
        "catalog_url": f"{ARCHIVE}/details/{identifier}", "metadata_url": f"{ARCHIVE}/metadata/{identifier}",
        "checked_at": _now(),
    }
    try:
        payload = _archive_metadata(identifier, client)
    except BookError as exc:
        return {**base, "extension": "", "available_formats": [], "edition_status": "not_verified",
                "acquisition_status": "metadata_error", "download": {"supported": False, "reason": exc.message},
                "metadata_error": exc.as_dict()}
    metadata = payload["metadata"]
    for field, api_field in (("title", "title"), ("author", "creator"), ("publisher", "publisher"), ("year", "date"), ("language", "language"), ("edition", "edition")):
        base[field] = _metadata_text(metadata.get(api_field)) or base[field]
    files = _archive_files(payload)
    chosen = files[0] if files else None
    base.update({
        "edition_status": "source_stated" if base["edition"] else "not_stated",
        "catalog_reference": _metadata_text(metadata.get("call_number")),
        "collection": metadata.get("collection", []),
        "rights_metadata": {
            "license_url": _metadata_text(metadata.get("licenseurl")),
            "statement": _metadata_text(metadata.get("rights")),
            "possible_status": _metadata_text(metadata.get("possible-copyright-status")),
            "region": _metadata_text(metadata.get("copyright-region")),
            "verification": "source_metadata_only_not_independent_authorization_check",
        },
        "available_formats": list(dict.fromkeys(entry["extension"] for entry in files)),
        "available_files": files, "extension": chosen["extension"] if chosen else "",
        "size": str(chosen["size"]) if chosen else "", "selected_file": chosen,
        "acquisition_status": "restricted" if _archive_restricted(payload) else ("public_file_listed_not_downloaded" if files else "no_supported_public_file"),
        "download": {"supported": bool(files)},
    })
    if not files:
        base["download"]["reason"] = "来源标记为受限/借阅条目，或没有公开且支持校验的文件。"
    return base


def archive_search(query, limit, client, collection=None):
    if collection and not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", collection):
        raise BookError("invalid_arguments", "--archive-collection 格式无效。")
    phrase = query.replace("\\", "\\\\").replace('"', '\\"')
    expression = f'(title:"{phrase}" OR creator:"{phrase}") AND mediatype:texts AND -access-restricted-item:true'
    if collection:
        expression += f" AND collection:{collection}"
    fields = ("identifier", "title", "creator", "publisher", "date", "language", "edition")
    params = [("q", expression), ("rows", str(limit)), ("page", "1"), ("output", "json")]
    params.extend(("fl[]", field) for field in fields)
    payload = client.read_json(f"{ARCHIVE}/advancedsearch.php?{urllib.parse.urlencode(params)}")
    response = payload.get("response")
    if payload.get("error") or not isinstance(response, dict) or not isinstance(response.get("docs"), list):
        raise BookError("invalid_response", "馆藏搜索 API 未返回有效结果列表。")
    documents = response["docs"]
    if not documents and response.get("numFound") != 0:
        raise BookError("invalid_response", "馆藏搜索缺少结果，不能判定为无结果。")
    results = []
    for offset, document in enumerate(documents[:limit]):
        if not isinstance(document, dict):
            raise BookError("invalid_response", "馆藏搜索条目结构无效。")
        if offset:
            client.sleep(0.25)
        results.append(_archive_result(document, client))
    return results


def _merge_results(groups, limit):
    """按源轮询合并，统一编号；同一源的相同记录去重。"""
    merged, seen = [], set()
    for offset in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if offset >= len(group):
                continue
            result = dict(group[offset])
            identity = (result["source"], result.get("md5") or (result.get("id"), result.get("hash")))
            if identity in seen:
                continue
            seen.add(identity)
            result["index"] = len(merged) + 1
            identity_text = json.dumps(identity, ensure_ascii=False, sort_keys=True)
            result["result_id"] = hashlib.sha256(identity_text.encode()).hexdigest()[:20]
            merged.append(result)
            if len(merged) >= limit:
                return merged
    return merged


class SessionStore:
    def __init__(self, work_dir=None):
        chosen = work_dir or os.environ.get("BOOK_SEARCH_WORK_DIR")
        self.root = _validate_user_path(chosen or (Path(tempfile.gettempdir()) / "mingxue-book-search"), "搜书工作区")
        self.sessions = self.root / "sessions"
        self.partials = self.root / "partials"
        self.validate_paths()
        self.sessions.mkdir(parents=True, exist_ok=True)
        self.partials.mkdir(parents=True, exist_ok=True)

    def validate_paths(self):
        root = _validate_user_path(self.root, "搜书工作区")
        for child in (self.sessions, self.partials):
            resolved = _validate_user_path(child, "搜书工作区子目录")
            if resolved.parent != root:
                raise BookError("unsafe_work_dir", "会话或部分下载目录不得通过链接跳出搜书工作区。")

    def save(self, record):
        self.validate_paths()
        session_id = uuid.uuid4().hex
        record = {"schema_version": 1, "session_id": session_id, **record}
        fd, temporary = tempfile.mkstemp(prefix="session-", suffix=".tmp", dir=self.sessions)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(record, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.sessions / f"{session_id}.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
        return record

    def load(self, session_id):
        if not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise BookError("invalid_session", "会话 ID 格式无效。")
        path = self.sessions / f"{session_id}.json"
        if path.resolve().parent != self.sessions.resolve():
            raise BookError("invalid_session", "会话文件路径超出工作区。")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise BookError("session_not_found", "此工作区不存在指定会话；请使用搜索时相同的 --work-dir。") from None
        except (ValueError, UnicodeError):
            raise BookError("invalid_session", "会话文件已损坏。") from None
        if not isinstance(record, dict) or record.get("schema_version") != 1 or record.get("session_id") != session_id:
            raise BookError("invalid_session", "会话内容无效。")
        if not isinstance(record.get("results"), list):
            raise BookError("invalid_session", "会话结果结构无效。")
        return record


def search(query, sources, limit, client, store, archive_collection=None):
    groups, source_states = [], []
    for source in dict.fromkeys(sources):
        if source == "annas":
            source_states.append({
                "source": source, "status": "manual", "result_count": 0,
                "checked_at": _now(), "network_checked": False,
                "capabilities": {"search": "manual_link", "download": "not_implemented"},
                "message": "仅提供人工搜索链接；未实现自动检索或下载，链接未实时验证。",
                "search_url": f"{ANNAS_SEARCH}?{urllib.parse.urlencode({'q': query})}",
            })
            continue
        try:
            if source == "archive":
                results = archive_search(query, limit, client, archive_collection)
            else:
                results = {"libgen": libgen_search, "zlib": zlib_search}[source](query, limit, client)
            groups.append(results)
            partial = any(result.get("acquisition_status") == "metadata_error" for result in results)
            source_states.append({
                "source": source, "status": "partial" if partial else ("ok" if results else "no_results"),
                "result_count": len(results), "checked_at": _now(), "network_checked": True,
                "capabilities": {"search": "automatic", "download": "public_api" if source == "archive" else "adapter"},
            })
        except BookError as exc:
            source_states.append({"source": source, "status": "error", "result_count": 0, "error": exc.as_dict(),
                                  "checked_at": _now(), "network_checked": exc.code not in {"credentials_missing", "model_id_required", "invalid_arguments"}})
    merged = _merge_results(groups, limit)
    has_error = any(item["status"] == "error" for item in source_states)
    has_manual = any(item["status"] == "manual" for item in source_states)
    has_partial = any(item["status"] == "partial" for item in source_states)
    if merged:
        status = "partial" if has_error or has_manual or has_partial else "ok"
    elif has_error:
        status = "error"
    elif has_manual:
        status = "manual"
    else:
        status = "no_results"
    # 即使无结果或失败也创建全新空会话；下载从不隐式读取「上一次」。
    record = store.save({
        "created_at": _now(), "query": query,
        "status": status, "sources": source_states, "results": merged,
    })
    return {**record, "count": len(merged), "limit": limit}


def sanitize_filename(value, *, fallback="book"):
    value = unicodedata.normalize("NFC", str(value or ""))
    value = "".join(char for char in value if unicodedata.category(char) != "Cf")
    # 先处理两种路径分隔符，避免 Linux 上漏掉 Windows 路径。
    value = re.split(r"[/\\]", value)[-1]
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", value).strip(" .")
    if not value or value in {".", ".."}:
        value = fallback
    device_stem = value.split(".", 1)[0].rstrip(" ")
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]", device_stem, re.I):
        value = "_" + value
    suffix = Path(value).suffix[:16]
    stem = value[:-len(suffix)] if suffix else value
    stem = stem[:150]
    while len((stem + suffix).encode("utf-8")) > 220:
        stem = stem[:-1]
    return (stem.rstrip(" .") or fallback) + suffix


def _server_filename(headers):
    content_disposition = headers.get("Content-Disposition", "")
    if not content_disposition:
        return ""
    message = Message()
    message["Content-Disposition"] = content_disposition
    filename = message.get_filename() or ""
    if isinstance(filename, tuple):
        filename = collapse_rfc2231_value(filename)
    filename = urllib.parse.unquote(filename)
    try:
        filename = filename.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return filename


def _download_filename(headers, result):
    expected = _extension(result.get("extension"))
    candidate = sanitize_filename(_server_filename(headers) or result.get("title") or result.get("md5") or "book")
    actual_suffix = _extension(Path(candidate).suffix)
    if actual_suffix and actual_suffix != expected:
        # 把元数据中本身带点的书名视为书名；服务端明确给出扩展名则必须一致。
        if _server_filename(headers):
            raise BookError("format_mismatch", "服务端文件扩展名与搜索结果格式不一致。")
        candidate += "." + expected
    elif not actual_suffix:
        candidate += "." + expected
    return sanitize_filename(candidate)


def _validate_file(path, extension, content_type):
    if path.stat().st_size == 0:
        raise BookError("empty_download", "源站返回空文件。")
    with path.open("rb") as file:
        head = file.read(8192)
    content_type = content_type.split(";", 1)[0].strip().lower()
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if content_type in {"text/html", "application/xhtml+xml", "application/json"} or re.match(
        br"(?:<!doctype\s+html|<html\b|<head\b|<body\b|<title\b|<form\b)", stripped
    ):
        raise BookError("not_a_book", "源站返回 HTML、JSON 或错误页面，未保存为图书文件。")
    if re.match(br"(?:access denied|forbidden|not found|error\b|service unavailable|too many requests|captcha\b)", stripped):
        raise BookError("not_a_book", "源站返回错误信息，未保存为图书文件。")
    if stripped.startswith(b"{") and re.search(br'"(?:error|errors)"\s*:|"success"\s*:\s*false', stripped):
        raise BookError("not_a_book", "源站返回 JSON 错误信息，未保存为图书文件。")
    valid = False
    if extension == "pdf":
        with path.open("rb") as file:
            file.seek(max(0, path.stat().st_size - 65536))
            tail = file.read()
        valid = bool(re.match(br"%PDF-\d\.\d", head)) and b"%%EOF" in tail
    elif extension in {"epub", "docx", "zip", "cbz"}:
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if extension == "epub":
                    info = archive.getinfo("mimetype")
                    valid = head.startswith(b"PK\x03\x04") and info.file_size <= 100 and archive.read(info) == b"application/epub+zip" and "META-INF/container.xml" in names
                elif extension == "docx":
                    valid = head.startswith(b"PK\x03\x04") and {"[Content_Types].xml", "word/document.xml"}.issubset(names)
                else:
                    valid = head.startswith((b"PK\x03\x04", b"PK\x05\x06"))
        except (zipfile.BadZipFile, KeyError, OSError, RuntimeError):
            valid = False
    elif extension == "djvu":
        valid = head.startswith(b"AT&TFORM") and head[12:16] in {b"DJVU", b"DJVM"}
    elif extension in {"mobi", "azw", "azw3"}:
        valid = head[60:68] == b"BOOKMOBI"
    elif extension in {"rar", "cbr"}:
        valid = head.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
    elif extension == "fb2":
        valid = bool(re.search(br"<(?:\w+:)?FictionBook\b", head))
    elif extension == "txt":
        try:
            encoding = "utf-16" if head.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
            text = decoder.decode(head, final=path.stat().st_size <= len(head))
            valid = bool(text.strip()) and not any(ord(char) < 32 and char not in "\n\r\t\f" for char in text)
            valid = valid and not re.search(r"<\s*(?:html|!doctype\s+html|error)\b", text, re.I)
            valid = valid and not re.match(r"\s*(?:access denied|forbidden|not found|error\b|service unavailable|too many requests|captcha\b)", text, re.I)
        except UnicodeError:
            valid = False
    if not valid:
        raise BookError("format_mismatch", f"文件内容与 {extension or '未知'} 格式不匹配，未作为成功文件保存。")


def _resolve_download(result, client):
    source = result.get("source")
    if source == "archive":
        identifier = _archive_identifier(result.get("id"))
        chosen = result.get("selected_file")
        if not isinstance(chosen, dict):
            raise BookError("download_unavailable", "此馆藏结果没有已列出的公开文件。")
        payload = _archive_metadata(identifier, client)
        current = next((entry for entry in _archive_files(payload) if entry["name"] == chosen.get("name")), None)
        if current is None:
            raise BookError("download_unavailable", "所选馆藏文件现已受限、移除或不再公开。")
        if current["extension"] != result.get("extension"):
            raise BookError("format_mismatch", "馆藏文件格式与所选结果不一致。")
        if chosen.get("md5") and current.get("md5") != chosen["md5"]:
            raise BookError("version_changed", "来源文件校验和已变化；请重新搜索并选择版本。")
        if chosen.get("size") != current["size"]:
            raise BookError("version_changed", "来源文件大小已变化；请重新搜索并选择版本。")
        result["expected_source_md5"] = current["md5"]
        result["expected_source_size"] = current["size"]
        return f"{ARCHIVE}/download/{identifier}/{urllib.parse.quote(current['name'], safe='/')}"
    if source == "libgen":
        md5 = result.get("md5", "")
        if not re.fullmatch(r"[a-f0-9]{32}", md5):
            raise BookError("invalid_session", "会话中的图书标识无效。")
        page = html.unescape(client.read_text(f"{LIBGEN}/ads.php?md5={md5}"))
        match = re.search(r"get\.php\?md5=" + md5 + r"&key=([A-Za-z0-9]+)", page, re.I)
        if not match:
            raise BookError("download_unavailable", "源站详情页未返回可用下载链接。")
        return f"{LIBGEN}/get.php?md5={md5}&key={match.group(1)}"
    if source == "zlib":
        credentials = _zlib_creds()
        host, book_id, book_hash = result.get("host"), str(result.get("id", "")), str(result.get("hash", ""))
        if host not in ZLIB_HOSTS or not re.fullmatch(r"[0-9]+", book_id) or not re.fullmatch(r"[a-zA-Z0-9]{1,128}", book_hash):
            raise BookError("invalid_session", "会话中的认证源标识无效。")
        payload = client.read_json(
            f"{host}/eapi/book/{book_id}/{book_hash}/file",
            headers={"Cookie": f"remix_userid={credentials['remix-userid']}; remix_userkey={credentials['remix-userkey']}"},
        )
        file_info = payload.get("file")
        if not payload.get("success") or not isinstance(file_info, dict) or not file_info.get("allowDownload"):
            raise BookError("download_unavailable", "认证源未允许下载或返回 API 错误。")
        link = file_info.get("downloadLink")
        if not isinstance(link, str):
            raise BookError("download_unavailable", "认证源未返回可用下载链接。")
        return _validate_url(link)
    raise BookError("download_unsupported", "此来源未实现自动下载。")


def _target_path(output_dir, filename):
    output_dir = _validate_user_path(output_dir, "下载输出目录")
    target = output_dir / sanitize_filename(filename)
    stem, suffix = target.stem, target.suffix
    counter = 1
    while os.path.lexists(target):
        target = output_dir / f"{stem} ({counter}){suffix}"
        counter += 1
    if target.resolve().parent != output_dir.resolve():
        raise BookError("unsafe_output_path", "文件目标超出用户指定的输出目录。")
    return target


def _commit_file(part, output_dir, filename):
    output_dir = _validate_user_path(output_dir, "下载输出目录")
    target = _target_path(output_dir, filename)
    ready = None
    published = False

    def publish(source):
        nonlocal published
        # 硬链接排他创建完整目标，不会出现空占位或覆盖用户文件。
        try:
            os.link(source, target)
        except OSError as exc:
            if os.name == "nt" and exc.errno not in {errno.EEXIST, errno.EXDEV} and getattr(exc, "winerror", None) != 17:
                # Windows rename 同样不会覆盖已有目标，用于不支持硬链接的文件系统。
                os.rename(source, target)
                published = True
                return
            raise
        published = True
        source.unlink()

    try:
        try:
            publish(part)
        except OSError as exc:
            if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
                raise
            # 跨盘时仅复制已验证完整文件；网络部分下载仍全部位于工作区。
            ready_fd, ready_name = tempfile.mkstemp(prefix=".book-ready-", suffix=".tmp", dir=output_dir)
            ready = Path(ready_name)
            with os.fdopen(ready_fd, "wb") as dest, part.open("rb") as source:
                shutil.copyfileobj(source, dest)
                dest.flush()
                os.fsync(dest.fileno())
            publish(ready)
            part.unlink()
        return target
    except BaseException:
        # 只清理本次已发布文件；若排他创建冲突，不触碰原有目标。
        if published:
            target.unlink(missing_ok=True)
        raise
    finally:
        if ready is not None:
            ready.unlink(missing_ok=True)


def download(session_id, index, output, client, store, max_bytes=DEFAULT_MAX_BYTES, format_=None):
    output_dir = _validate_user_path(output, "下载输出目录")
    store.validate_paths()
    record = store.load(session_id)
    if not 1 <= index <= len(record["results"]):
        raise BookError("invalid_index", "下载序号超出此会话的结果范围。")
    result = record["results"][index - 1]
    if not isinstance(result, dict) or result.get("index") != index:
        raise BookError("invalid_session", "会话结果序号无效。")
    result = dict(result)
    if format_ is not None:
        if result.get("source") == "archive":
            chosen = next((entry for entry in result.get("available_files", []) if isinstance(entry, dict) and entry.get("extension") == format_), None)
            if chosen is None:
                raise BookError("format_unavailable", "此会话条目没有所选公开格式；请查看 available_formats。")
            result.update({"selected_file": chosen, "extension": format_})
        elif format_ != result.get("extension"):
            raise BookError("format_unavailable", "此来源结果仅支持搜索中列出的单一格式。")
    extension = _extension(result.get("extension"))
    if extension not in SUPPORTED_FORMATS:
        raise BookError("download_unsupported", "未实现此文件格式的内容校验，请人工获取。")
    output_dir.mkdir(parents=True, exist_ok=True)
    link = _resolve_download(result, client)

    def attempt():
        store.validate_paths()
        fd, part_name = tempfile.mkstemp(prefix=f"{session_id[:8]}-", suffix=".part", dir=store.partials)
        part = Path(part_name)
        digest = hashlib.sha256()
        source_digest = hashlib.md5(usedforsecurity=False)
        total = 0
        try:
            with os.fdopen(fd, "wb") as destination, client.open_once(link) as response:
                filename = _download_filename(response.headers, result)
                raw_size = response.headers.get("Content-Length")
                if raw_size is not None:
                    try:
                        declared_size = int(raw_size)
                    except (ValueError, TypeError):
                        raise BookError("invalid_response", "源站 Content-Length 无效。") from None
                    if declared_size < 0 or declared_size > max_bytes:
                        raise BookError("download_too_large", "源站文件超过下载大小限制。")
                while True:
                    try:
                        chunk = response.read(64 * 1024)
                    except (OSError, http.client.HTTPException, EOFError):
                        raise BookError("interrupted_download", "下载流中断，临时文件已清理。", retryable=True) from None
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise BookError("download_too_large", "源站文件超过下载大小限制。")
                    digest.update(chunk)
                    source_digest.update(chunk)
                    destination.write(chunk)
                _check_content_length(response.headers, total)
                if result.get("expected_source_size") is not None and total != result["expected_source_size"]:
                    raise BookError("incomplete_download", "收到的文件大小与馆藏元数据不一致。", retryable=True)
                if result.get("expected_source_md5") and source_digest.hexdigest() != result["expected_source_md5"]:
                    raise BookError("checksum_mismatch", "文件内容与来源校验和不一致，未作为成功文件保存。")
                destination.flush()
                os.fsync(destination.fileno())
                content_type = response.headers.get("Content-Type", "")
            _validate_file(part, extension, content_type)
            target = _commit_file(part, output_dir, filename)
            return {
                "status": "ok", "session_id": session_id, "index": index,
                "source": result["source"], "path": str(target), "bytes": total,
                "sha256": digest.hexdigest(), "extension": extension,
                "checked_at": _now(), "acquisition_status": "downloaded_and_content_verified",
                "title": result.get("title", ""), "version_id": result.get("version_id", ""),
                "edition": result.get("edition", ""), "edition_status": result.get("edition_status", "not_stated"),
                "catalog_url": result.get("catalog_url", ""),
                "source_md5": result.get("expected_source_md5", ""),
                "source_checksum_status": "matched" if result.get("expected_source_md5") else "not_provided",
            }
        except (http.client.HTTPException, ConnectionError, TimeoutError, EOFError):
            raise BookError("interrupted_download", "下载流中断，临时文件已清理。", retryable=True) from None
        finally:
            part.unlink(missing_ok=True)

    return client.run(attempt)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise BookError("invalid_arguments", message)


def _parser():
    parser = _ArgumentParser(prog="book-search", description="搜书：搜索与下载分开执行，输出 JSON。")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_ArgumentParser)
    search_parser = commands.add_parser("search", help="搜索并保存独立会话")
    search_parser.add_argument("query", nargs="+", help="书名或作者关键词")
    search_parser.add_argument("--sources", nargs="+", choices=("archive", "libgen", "annas", "zlib"), default=["archive"])
    search_parser.add_argument("--limit", type=int, default=15, help="合并后最多结果数，1 到 100（默认 15）")
    search_parser.add_argument("--archive-collection", help="仅限制 archive 的馆藏集合，例如 gutenberg")
    download_parser = commands.add_parser("download", help="从指定会话下载一条结果")
    download_parser.add_argument("index", type=int, help="该会话中全局连续编号，起始为 1")
    download_parser.add_argument("--session", required=True, help="search 返回的 session_id")
    download_parser.add_argument("-o", "--output", required=True, help="用户指定的最终输出目录")
    download_parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="最大下载字节数（默认 512 MiB）")
    download_parser.add_argument("--format", choices=sorted(SUPPORTED_FORMATS), help="从 archive available_formats 选择公开格式；其他源仅能使用原格式")
    for subparser in (search_parser, download_parser):
        subparser.add_argument("--work-dir", help="会话和部分下载工作区；默认 BOOK_SEARCH_WORK_DIR 或系统临时目录")
        subparser.add_argument("--timeout", type=float, default=30, help="每次网络操作超时秒数，1 到 120（默认 30）")
        subparser.add_argument("--retries", type=int, default=1, help="额外重试次数，0 到 3（默认 1）")
        subparser.add_argument("--agent-model", default=os.environ.get("BOOK_SEARCH_AGENT_MODEL"),
                               help="实际工具执行模型；也可设置 BOOK_SEARCH_AGENT_MODEL。archive 缺少此值时拒绝请求")
    return parser


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        if args.command == "search" and not 1 <= args.limit <= 100:
            raise BookError("invalid_arguments", "--limit 必须在 1 到 100 之间。")
        if args.command == "search" and args.archive_collection and not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", args.archive_collection):
            raise BookError("invalid_arguments", "--archive-collection 格式无效。")
        if args.command == "download" and not 1 <= args.max_bytes <= 2 * 1024 * 1024 * 1024:
            raise BookError("invalid_arguments", "--max-bytes 必须在 1 到 2147483648 之间。")
        # 下载输出也在创建缓存、创建目录和连接网络之前检查。
        if args.command == "download":
            _validate_user_path(args.output, "下载输出目录")
        store = SessionStore(args.work_dir)
        client = HttpClient(args.timeout, args.retries, agent_model=args.agent_model)
        if args.command == "search":
            if "archive" in args.sources:
                _require_archive_identity(ARCHIVE, client.agent_model)
            query = " ".join(args.query).strip()
            if not query:
                raise BookError("invalid_arguments", "搜索关键词不能为空。")
            result = search(query, args.sources, args.limit, client, store, args.archive_collection)
            exit_code = 3 if result["status"] == "error" else 0
        else:
            result = download(args.session, args.index, args.output, client, store, args.max_bytes, args.format)
            exit_code = 0
        print(json.dumps(result, ensure_ascii=False))
        return exit_code
    except BookError as exc:
        print(json.dumps({"status": "error", "error": exc.as_dict()}, ensure_ascii=False))
        return 2 if exc.code == "invalid_arguments" else 1
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        # 不回显源站正文、认证头或凭据；错误仍为可解析 JSON，退出非零。
        print(json.dumps({"status": "error", "error": {"code": "local_error", "message": f"本地文件或数据处理失败（{type(exc).__name__}）。"}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
