from datetime import datetime, timezone
from html.parser import HTMLParser

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import REQUEST_TIMEOUT, USER_AGENT


def _session():
    retry = Retry(
        total=1,
        connect=1,
        read=0,
        status=1,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def clean_html(value):
    if not value:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(value)
        return " ".join(" ".join(parser.parts).split())
    except Exception:
        return str(value)[:2000]


def parse_duration(value):
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return int(value)
        parts = str(value).strip().split(":")
        total = 0
        for part in parts:
            total = total * 60 + int(float(part))
        return total if total >= 0 else None
    except (TypeError, ValueError):
        return None


def _published(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _audio_url(entry):
    for enclosure in entry.get("enclosures", []):
        href = enclosure.get("href") or enclosure.get("url")
        if href:
            return href
    for link in entry.get("links", []):
        if link.get("type", "").startswith("audio/"):
            return link.get("href")
    return None


def fetch_episodes(feed_url: str, max_episodes: int = 20):
    # Separate connect/read limits prevent one unresponsive publisher from
    # holding up the whole discovery run indefinitely.
    timeout = (5, min(10, max(3, REQUEST_TIMEOUT)))
    with _session() as session:
        response = session.get(feed_url, timeout=timeout)
        response.raise_for_status()

    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Feed could not be parsed: {parsed.bozo_exception}")

    episodes = []
    for entry in parsed.entries[:max_episodes]:
        guid = (
            entry.get("id")
            or entry.get("guid")
            or entry.get("link")
            or entry.get("title")
        )
        if not guid:
            continue

        duration = entry.get("itunes_duration")
        if duration is None:
            duration = entry.get("duration")

        episodes.append({
            "episode_guid": str(guid),
            "title": entry.get("title", "Untitled episode"),
            "description": clean_html(
                entry.get("summary") or entry.get("description") or ""
            )[:5000],
            "published_at": _published(entry),
            "duration_seconds": parse_duration(duration),
            "episode_url": entry.get("link"),
            "audio_url": _audio_url(entry),
        })
    return episodes
