from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from config.keywords import BASE_KEYWORDS
from config.sources import (
    CCF_NETWORK_SECURITY_REFERENCE,
    SOURCE_DEFINITIONS as RAW_SOURCE_DEFINITIONS,
)

try:
    import certifi
except ImportError:  # pragma: no cover - optional dependency fallback
    certifi = None


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "tracker_state.json"

CACHE_TTL_SECONDS = 15 * 60
RECENT_DAYS = 365
USER_AGENT = "Mozilla/5.0 (compatible; AI-Safety-Tracker/1.0; +https://github.com/openai)"

KEYWORD_PATTERNS = [re.compile(re.escape(keyword), re.IGNORECASE) for keyword in BASE_KEYWORDS]


@dataclass(frozen=True)
class Source:
    source_id: str
    name: str
    category: str
    description: str
    url: str
    fetcher: str
    extra: dict


SOURCE_DEFINITIONS = [Source(**source_config) for source_config in RAW_SOURCE_DEFINITIONS]
SOURCE_MAP = {source.source_id: source for source in SOURCE_DEFINITIONS}
FETCHERS: dict[str, Callable[[Source], list[dict]]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def recent_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)


def slug_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_date_string(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def date_sort_value(value: str) -> float:
    parsed = parse_date_string(value)
    if parsed == datetime.min.replace(tzinfo=timezone.utc):
        return 0.0
    return parsed.timestamp()


def score_text(value: str) -> int:
    lowered = value.lower()
    return sum(1 for pattern in KEYWORD_PATTERNS if pattern.search(lowered))


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    ssl_context = ssl.create_default_context(cafile=certifi.where()) if certifi else None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=35, context=ssl_context) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                retry_after = exc.headers.get("Retry-After")
                sleep_seconds = float(retry_after) if retry_after and retry_after.isdigit() else 2 + attempt * 2
                time.sleep(sleep_seconds)
                continue
            raise


def crossref_date_parts(item: dict) -> tuple[int, int, int] | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        date_parts = item.get(key, {}).get("date-parts", [])
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            year = parts[0]
            month = parts[1] if len(parts) > 1 else 1
            day = parts[2] if len(parts) > 2 else 1
            return year, month, day
    return None


def crossref_date_text(item: dict) -> str:
    parts = crossref_date_parts(item)
    if not parts:
        return ""
    year, month, day = parts
    return f"{year:04d}-{month:02d}-{day:02d}"


def crossref_link(item: dict) -> str:
    if item.get("URL"):
        return item["URL"]
    doi = normalize_text(item.get("DOI", ""))
    return f"https://doi.org/{doi}" if doi else ""


def parse_crossref_journal(source: Source) -> list[dict]:
    limit = source.extra.get("limit", 25)
    from_date = recent_cutoff().date().isoformat()
    issn = source.extra["issn"]
    api_url = (
        f"https://api.crossref.org/journals/{urllib.parse.quote(issn)}/works"
        f"?filter=from-pub-date:{from_date}"
        f"&sort=published&order=desc&rows={limit}"
    )
    payload = fetch_json(api_url)
    works = payload.get("message", {}).get("items", [])
    items: list[dict] = []
    for work in works:
        published = crossref_date_text(work)
        if not published:
            continue
        if parse_date_string(published) < recent_cutoff():
            continue

        title_list = work.get("title") or []
        title = normalize_text(title_list[0] if title_list else "")
        if not title:
            continue

        authors = []
        for author in work.get("author", []):
            given = normalize_text(author.get("given", ""))
            family = normalize_text(author.get("family", ""))
            full_name = normalize_text(f"{given} {family}")
            if full_name:
                authors.append(full_name)

        abstract = normalize_text(re.sub(r"<[^>]+>", " ", work.get("abstract", "")))
        doi = normalize_text(work.get("DOI", ""))
        items.append(
            {
                "id": slug_hash(f"{source.source_id}:{doi or title}:{published}"),
                "title": title,
                "authors": ", ".join(authors),
                "summary": abstract
                or f"{source.extra['full_name']} · CCF {source.extra['ccf_tier']} 类 · 仅展示近 1 年论文。",
                "link": crossref_link(work) or source.url,
                "source_url": source.url,
                "published": published,
                "topic": f"CCF {source.extra['ccf_tier']}",
                "subcategory": source.extra["full_name"],
                "match_score": max(score_text(f"{title} {abstract}"), 1),
                "content_type": "paper",
            }
        )

    items.sort(key=lambda item: (-date_sort_value(item["published"]), item["title"]))
    return items


FETCHERS.update(
    {
        "crossref_journal": parse_crossref_journal,
    }
)


class TrackerStore:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.lock = threading.Lock()
        self.state = self._load()

    def _load(self) -> dict:
        if not self.state_path.exists():
            return {"sources": {}}
        with self.state_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(self.state, file, ensure_ascii=False, indent=2)

    def get_cached_source(self, source_id: str) -> dict | None:
        with self.lock:
            return self.state.get("sources", {}).get(source_id)

    def refresh_source(self, source: Source, force: bool = False) -> dict:
        with self.lock:
            source_state = self.state.setdefault("sources", {}).setdefault(source.source_id, {})
            fetched_at = source_state.get("fetched_at")
            if fetched_at and not force:
                cached_at = datetime.fromisoformat(fetched_at)
                age = (datetime.now(timezone.utc) - cached_at).total_seconds()
                if age < CACHE_TTL_SECONDS and source_state.get("items"):
                    return source_state

        fetcher = FETCHERS[source.fetcher]
        items = fetcher(source)

        with self.lock:
            source_state = self.state.setdefault("sources", {}).setdefault(source.source_id, {})
            previously_seen = set(source_state.get("seen_ids", []))
            current_ids = [item["id"] for item in items]
            seen_ids = sorted(previously_seen.union(current_ids))
            for item in items:
                item["is_new"] = item["id"] not in previously_seen
            source_state.update(
                {
                    "fetched_at": now_iso(),
                    "items": items,
                    "seen_ids": seen_ids,
                    "error": "",
                }
            )
            self._save()
            return source_state

    def refresh_all(self, force: bool = False) -> dict:
        payload = {"sources": [], "generated_at": now_iso()}
        for source in SOURCE_DEFINITIONS:
            try:
                source_state = self.refresh_source(source, force=force)
                payload["sources"].append(build_source_payload(source, source_state))
            except Exception as exc:  # noqa: BLE001
                payload["sources"].append(
                    build_source_payload(
                        source,
                        {
                            "fetched_at": "",
                            "items": [],
                            "error": str(exc),
                        },
                    )
                )
        return payload


def build_source_payload(source: Source, state: dict) -> dict:
    return {
        "id": source.source_id,
        "name": source.name,
        "category": source.category,
        "description": f"{source.description} {CCF_NETWORK_SECURITY_REFERENCE}",
        "url": source.url,
        "fetched_at": state.get("fetched_at", ""),
        "count": len(state.get("items", [])),
        "error": state.get("error", ""),
        "items": state.get("items", []),
    }


STORE = TrackerStore(STATE_PATH)


class TrackerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/sources":
            self.respond_json(
                {
                    "sources": [
                        build_source_payload(source, STORE.get_cached_source(source.source_id) or {})
                        for source in SOURCE_DEFINITIONS
                    ]
                }
            )
            return
        if parsed.path == "/api/data":
            force = query.get("refresh", ["0"])[0] == "1"
            source_id = query.get("source", [""])[0]
            if source_id:
                source = SOURCE_MAP.get(source_id)
                if not source:
                    self.send_error(HTTPStatus.NOT_FOUND, "Unknown source")
                    return
                try:
                    source_state = STORE.refresh_source(source, force=force)
                    self.respond_json({"generated_at": now_iso(), "sources": [build_source_payload(source, source_state)]})
                except Exception as exc:  # noqa: BLE001
                    self.respond_json(
                        {
                            "generated_at": now_iso(),
                            "sources": [build_source_payload(source, {"error": str(exc), "items": [], "fetched_at": ""})],
                        }
                    )
                return
            payload = STORE.refresh_all(force=force)
            self.respond_json(payload)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, fmt: str, *args) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {fmt % args}")

    def respond_json(self, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), TrackerHandler)
    print(f"AI Safety Tracker running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    port_value = os.environ.get("PORT")
    run_server(
        host=os.environ.get("HOST", "0.0.0.0" if port_value else "127.0.0.1"),
        port=int(port_value or "8765"),
    )
