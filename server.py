from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup

from config.keywords import BASE_KEYWORDS
from config.sources import MARKDOWN_SOURCE_URL, SOURCE_DEFINITIONS as RAW_SOURCE_DEFINITIONS


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "tracker_state.json"

CACHE_TTL_SECONDS = 15 * 60
ARXIV_MAX_RESULTS = 25
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


def slug_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_loose_date(value: str) -> datetime:
    for fmt in ("%b %d, %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.min


def date_sort_value(value: str) -> float:
    parsed = parse_loose_date(value)
    if parsed == datetime.min:
        return 0.0
    return parsed.timestamp()


def score_text(value: str) -> int:
    lowered = value.lower()
    return sum(1 for pattern in KEYWORD_PATTERNS if pattern.search(lowered))


def is_relevant(text: str) -> bool:
    return score_text(text) > 0


def fetch_text(url: str) -> str:
    command = [
        "curl",
        "-L",
        "--silent",
        "--show-error",
        "--max-time",
        "35",
        "-A",
        USER_AGENT,
        url,
    ]
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    return completed.stdout


def clean_markdown_title(line: str) -> tuple[str, str | None]:
    topic_match = re.search(r"\*\*\[Topic:\s*([^\]]+)\]\*\*", line)
    topic = topic_match.group(1).strip() if topic_match else None
    title = re.sub(r"\*\*\[Topic:[^\]]+\]\*\*", "", line)
    title = re.sub(r"\[\[.*?\]\]\(.*?\)", "", title)
    title = title.replace("**", "")
    title = normalize_text(title.strip("- ").strip())
    return title, topic


def parse_big4_markdown(source: Source) -> list[dict]:
    markdown = fetch_text(MARKDOWN_SOURCE_URL)
    lines = markdown.splitlines()
    heading = source.extra["heading"]
    in_section = False
    subsection = ""
    items: list[dict] = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if line == heading:
            in_section = True
            index += 1
            continue
        if in_section and line.startswith("## ") and line != heading:
            break
        if not in_section:
            index += 1
            continue
        if line.startswith("### "):
            subsection = normalize_text(line.removeprefix("### "))
            index += 1
            continue
        if line.startswith("- "):
            title, topic = clean_markdown_title(line)
            pdf_link = ""
            code_link = ""
            authors = ""
            cursor = index + 1
            while cursor < len(lines):
                follower = lines[cursor]
                stripped = follower.strip()
                if follower.startswith("- ") or stripped.startswith("### ") or stripped.startswith("## "):
                    break
                if "[[pdf]](" in stripped:
                    pdf_match = re.search(r"\[\[pdf\]\]\(([^)]+)\)", stripped)
                    if pdf_match:
                        pdf_link = pdf_match.group(1)
                    code_match = re.search(r"\[\[Code\]\]\(([^)]+)\)", stripped)
                    if code_match:
                        code_link = code_match.group(1)
                elif stripped.startswith("- "):
                    authors = normalize_text(stripped.removeprefix("- "))
                elif stripped.startswith("-"):
                    authors = normalize_text(stripped.removeprefix("-"))
                elif stripped.startswith("*"):
                    authors = normalize_text(stripped.removeprefix("*"))
                elif stripped.startswith(" -"):
                    authors = normalize_text(stripped.split("-", 1)[1])
                cursor += 1
            if authors:
                authors = re.sub(r"\s+\*.*$", "", authors).strip(" .")
            year_match = re.search(r"(\d{4})", subsection)
            year = year_match.group(1) if year_match else ""
            item = {
                "id": slug_hash(f"{source.source_id}:{title}:{pdf_link or code_link}"),
                "title": title,
                "authors": authors,
                "summary": f"{subsection} · Topic: {topic}" if topic else subsection,
                "link": pdf_link or code_link or source.url,
                "source_url": source.url,
                "published": year,
                "topic": topic or "",
                "subcategory": subsection,
                "match_score": 10,
                "content_type": "paper",
            }
            if title:
                items.append(item)
            index = cursor
            continue
        index += 1
    return items


def parse_pmlr_html(source: Source) -> list[dict]:
    html = fetch_text(source.url)
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for paper in soup.select("div.paper"):
        title_node = paper.select_one("p.title")
        authors_node = paper.select_one("p.authors")
        if not title_node:
            continue
        title = normalize_text(title_node.get_text(" ", strip=True))
        authors = normalize_text(authors_node.get_text(" ", strip=True)) if authors_node else ""
        text = normalize_text(paper.get_text(" ", strip=True))
        if not is_relevant(f"{title} {text}"):
            continue
        links = paper.select("a[href]")
        abs_link = source.url
        pdf_link = ""
        for link in links:
            href = urllib.parse.urljoin(source.url, link["href"])
            label = normalize_text(link.get_text(" ", strip=True)).lower()
            if label == "abs":
                abs_link = href
            if "pdf" in label:
                pdf_link = href
        score = score_text(f"{title} {text}")
        items.append(
            {
                "id": slug_hash(f"{source.source_id}:{title}:{abs_link}"),
                "title": title,
                "authors": authors,
                "summary": "ICML 2025 proceedings 中按 AI 安全关键词命中的论文。",
                "link": abs_link or pdf_link or source.url,
                "source_url": source.url,
                "published": "2025",
                "topic": "",
                "subcategory": "ICML 2025",
                "match_score": score,
                "content_type": "paper",
            }
        )
    items.sort(key=lambda item: (-item["match_score"], item["title"]))
    return items[: source.extra["limit"]]


def parse_cvpr_html(source: Source) -> list[dict]:
    html = fetch_text(source.url)
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for title_node in soup.select("dt.ptitle"):
        title = normalize_text(title_node.get_text(" ", strip=True))
        if not title:
            continue
        author_node = title_node.find_next_sibling("dd")
        authors = normalize_text(author_node.get_text(" ", strip=True)) if author_node else ""
        link_node = title_node.find("a", href=True)
        link = urllib.parse.urljoin(source.url, link_node["href"]) if link_node else source.url
        score = score_text(f"{title} {authors}")
        if score == 0:
            continue
        items.append(
            {
                "id": slug_hash(f"{source.source_id}:{title}:{link}"),
                "title": title,
                "authors": authors,
                "summary": "CVPR 2025 Open Access 中按计算机视觉安全关键词命中的论文。",
                "link": link,
                "source_url": source.url,
                "published": "2025",
                "topic": "",
                "subcategory": "CVPR 2025",
                "match_score": score,
                "content_type": "paper",
            }
        )
    items.sort(key=lambda item: (-item["match_score"], item["title"]))
    return items[: source.extra["limit"]]


def parse_arxiv_api(source: Source) -> list[dict]:
    query = urllib.parse.quote(source.extra["query"])
    limit = source.extra.get("limit", ARXIV_MAX_RESULTS)
    url = f"https://export.arxiv.org/api/query?search_query={query}&start=0&max_results={limit}&sortBy=submittedDate&sortOrder=descending"
    xml_text = fetch_text(url)
    namespace = {
        "atom": "http://www.w3.org/2005/Atom",
    }
    root = ET.fromstring(xml_text)
    items: list[dict] = []
    for entry in root.findall("atom:entry", namespace):
        title = normalize_text(entry.findtext("atom:title", default="", namespaces=namespace))
        summary = normalize_text(entry.findtext("atom:summary", default="", namespaces=namespace))
        published = normalize_text(entry.findtext("atom:published", default="", namespaces=namespace))
        link = normalize_text(entry.findtext("atom:id", default="", namespaces=namespace))
        authors = ", ".join(
            normalize_text(author.findtext("atom:name", default="", namespaces=namespace))
            for author in entry.findall("atom:author", namespace)
        )
        pdf_link = link.replace("/abs/", "/pdf/") + ".pdf" if "/abs/" in link else link
        score = score_text(f"{title} {summary}")
        items.append(
            {
                "id": slug_hash(f"{source.source_id}:{link}"),
                "title": title,
                "authors": authors,
                "summary": summary,
                "link": pdf_link or link,
                "source_url": source.url,
                "published": published[:10],
                "topic": "",
                "subcategory": source.name,
                "match_score": score or 1,
                "content_type": "paper",
            }
        )
    return items


def parse_anthropic_html(source: Source) -> list[dict]:
    html = fetch_text(source.url)
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for link_node in soup.select('a[href^="/research/"]'):
        href = link_node.get("href", "")
        if "/research/team/" in href:
            continue
        title_node = link_node.select_one("h2, h3, h4")
        summary_node = link_node.select_one("p")
        date_node = link_node.select_one("time")
        tag_node = link_node.select_one("span")
        title = normalize_text(title_node.get_text(" ", strip=True)) if title_node else normalize_text(link_node.get_text(" ", strip=True))
        summary = normalize_text(summary_node.get_text(" ", strip=True)) if summary_node else ""
        tag = normalize_text(tag_node.get_text(" ", strip=True)) if tag_node else ""
        date_text = normalize_text(date_node.get_text(" ", strip=True)) if date_node else ""
        score = score_text(f"{title} {summary} {tag}")
        if score == 0:
            continue
        items.append(
            {
                "id": slug_hash(f"{source.source_id}:{href}"),
                "title": title,
                "authors": "Anthropic",
                "summary": summary,
                "link": urllib.parse.urljoin("https://www.anthropic.com", href),
                "source_url": source.url,
                "published": date_text,
                "topic": tag,
                "subcategory": tag or source.name,
                "match_score": score,
                "content_type": "report",
            }
        )
    items.sort(key=lambda item: (-item["match_score"], -date_sort_value(item["published"])))
    return items[: source.extra["limit"]]


def parse_deepmind_html(source: Source) -> list[dict]:
    html = fetch_text(source.url)
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for link_node in soup.select('a[href*="/research/publications/"]'):
        href = link_node.get("href", "")
        if href.endswith("/research/publications/") or href == "/research/publications/":
            continue
        title_node = link_node.select_one(".list-group__description")
        date_node = link_node.select_one(".list-group__date")
        title = normalize_text(title_node.get_text(" ", strip=True)) if title_node else normalize_text(link_node.get_text(" ", strip=True))
        published = normalize_text(date_node.get_text(" ", strip=True)) if date_node else ""
        score = score_text(title)
        if score == 0:
            continue
        items.append(
            {
                "id": slug_hash(f"{source.source_id}:{href}"),
                "title": title,
                "authors": "Google DeepMind",
                "summary": "DeepMind 官方 publications 页中按 safety / alignment 关键词命中的条目。",
                "link": href,
                "source_url": source.url,
                "published": published,
                "topic": "",
                "subcategory": source.name,
                "match_score": score,
                "content_type": "report",
            }
        )
    items.sort(key=lambda item: (-item["match_score"], -date_sort_value(item["published"])))
    return items[: source.extra["limit"]]


FETCHERS.update(
    {
        "big4_markdown": parse_big4_markdown,
        "pmlr_html": parse_pmlr_html,
        "cvpr_html": parse_cvpr_html,
        "arxiv_api": parse_arxiv_api,
        "anthropic_html": parse_anthropic_html,
        "deepmind_html": parse_deepmind_html,
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
        "description": source.description,
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
            self.respond_json({"sources": [build_source_payload(source, STORE.get_cached_source(source.source_id) or {}) for source in SOURCE_DEFINITIONS]})
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
                    self.respond_json({"generated_at": now_iso(), "sources": [build_source_payload(source, {"error": str(exc), "items": [], "fetched_at": ""})]})
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
