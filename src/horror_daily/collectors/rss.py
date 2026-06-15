from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from horror_daily.collectors.base import CollectionResult
from horror_daily.models import InfoType, NewsItem, SourceFailure
from horror_daily.services.http import build_client, describe_http_error
from horror_daily.services.retry import network_retry

logger = logging.getLogger(__name__)


class RssCollector:
    def __init__(self, config: dict):
        self.config = config
        runtime = config.get("runtime", {})
        self.attempts = runtime.get("retry_attempts", 3)
        self.days_back = runtime.get("days_back", 7)
        self.max_items = runtime.get("max_items_per_source", 30)
        self.concurrency = runtime.get("rss_concurrency", 4)
        kw = config.get("keywords", {})
        self.match_terms = [*kw.get("horror", []), *kw.get("tracked_series", []), *kw.get("pc", [])]
        self.event_terms = kw.get("events", {})

    def collect(self) -> CollectionResult:
        result = CollectionResult()
        sources = [source for source in self.config.get("rss_sources", []) if source.get("enabled", True)]
        with build_client(self.config) as client:
            with ThreadPoolExecutor(max_workers=max(1, self.concurrency)) as executor:
                future_map = {executor.submit(self._collect_source, client, source): source for source in sources}
                for future in as_completed(future_map):
                    source = future_map[future]
                    try:
                        result.items.extend(future.result())
                    except Exception as exc:
                        message = describe_http_error(exc)
                        logger.warning("RSS source failed: %s: %s", source.get("name"), message)
                        result.failures.append(SourceFailure(source=source.get("name", "RSS"), error=message))
        return result

    def _fetch(self, client: httpx.Client, url: str) -> bytes:
        @network_retry(self.attempts)
        def do_fetch() -> bytes:
            response = client.get(url)
            response.raise_for_status()
            return response.content

        return do_fetch()

    def _collect_source(self, client: httpx.Client, source: dict) -> list[NewsItem]:
        content = self._fetch(client, source["url"])
        feed = feedparser.parse(content)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_back)
        items: list[NewsItem] = []
        for entry in feed.entries[: self.max_items]:
            published = self._entry_date(entry)
            if published < cutoff:
                continue
            title = entry.get("title", "").strip()
            summary = self._clean(entry.get("summary", "") or entry.get("description", ""))
            text = f"{title} {summary}".lower()
            if not self._is_relevant(text):
                continue
            game_name, confidence = self._guess_game_name(title)
            items.append(
                NewsItem(
                    title=title,
                    url=entry.get("link", ""),
                    source=source.get("name", "RSS"),
                    published_at=published,
                    summary=summary[:1200],
                    game_name=game_name,
                    original_name=game_name,
                    tags=self._matched_terms(text),
                    info_type=self._guess_info_type(text),
                    source_reliability=int(source.get("reliability", 70)),
                    raw={"rss_source": source.get("url"), "language": source.get("language")},
                    item_title=title,
                    source_title=title,
                    game_title=game_name,
                    game_title_confidence=confidence,
                    series=self._guess_series(text),
                )
            )
        return items

    def _entry_date(self, entry) -> datetime:
        raw = entry.get("published") or entry.get("updated") or ""
        if raw:
            try:
                parsed = parsedate_to_datetime(raw)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        return datetime.now(timezone.utc)

    def _is_relevant(self, text: str) -> bool:
        horror_hit = any(term.lower() in text for term in self.config["keywords"].get("horror", []))
        series_hit = any(term.lower() in text for term in self.config["keywords"].get("tracked_series", []))
        pc_hit = any(term.lower() in text for term in self.config["keywords"].get("pc", []))
        return (horror_hit or series_hit) and (pc_hit or series_hit or "game" in text)

    def _matched_terms(self, text: str) -> list[str]:
        return sorted({term for term in self.match_terms if term.lower() in text})[:12]

    def _guess_info_type(self, text: str) -> InfoType:
        for key, terms in self.event_terms.items():
            if any(term.lower() in text for term in terms):
                return InfoType(key)
        return InfoType.NEWS

    def _guess_game_name(self, title: str) -> tuple[str, float]:
        quoted_patterns = [
            r"['\"“”‘’『』「」]([^'\"“”‘’『』「」]{2,80})['\"“”‘’『』「」]",
            r"《([^》]{2,80})》",
        ]
        for pattern in quoted_patterns:
            match = re.search(pattern, title)
            if match:
                candidate = self._clean_candidate(match.group(1))
                if candidate:
                    return candidate, 0.8

        known = self._known_title_from_keywords(title)
        if known:
            return known, 0.75

        conservative_patterns = [
            r"^([A-Z][A-Za-z0-9:'.!,& -]{2,70})\s+(?:gets|adds|reveals|launches|confirms|announces|will)\b",
            r"\b(?:for|of|in)\s+([A-Z][A-Za-z0-9:'.!,& -]{2,60})(?:\s+gets|\s+adds|\s+reveals|\s+launches|\s+confirms|\s+demo|\s+trailer|\s+update|$)",
        ]
        for pattern in conservative_patterns:
            match = re.search(pattern, title)
            if match:
                candidate = self._clean_candidate(match.group(1))
                if candidate:
                    return candidate, 0.65
        return "", 0

    def _known_title_from_keywords(self, title: str) -> str:
        lower = title.lower()
        candidates = sorted(
            set(self.config.get("keywords", {}).get("tracked_series", [])),
            key=lambda value: len(value),
            reverse=True,
        )
        for series in candidates:
            if series.lower() in lower:
                return series
        return ""

    def _clean_candidate(self, value: str) -> str:
        candidate = value.strip(" -:|")
        if not candidate or self._looks_like_sentence(candidate):
            return ""
        return candidate[:120]

    def _guess_series(self, text: str) -> str:
        for series in self.config.get("keywords", {}).get("tracked_series", []):
            if series.lower() in text:
                return series
        return ""

    def _looks_like_sentence(self, value: str) -> bool:
        words = value.split()
        sentence_words = {"announced", "revealed", "reportedly", "confirms", "everything", "during", "will", "why"}
        return len(words) > 8 or any(word.lower().strip(",:") in sentence_words for word in words)

    def _clean(self, value: str) -> str:
        return " ".join(value.replace("\n", " ").split())
