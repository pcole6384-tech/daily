from __future__ import annotations

import hashlib
import re

from horror_daily.models import NewsItem


def normalize_key(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"https?://(www\.)?", "", value)
    value = re.sub(r"[?#].*$", "", value)
    value = re.sub(r"\W+", " ", value)
    return value.strip()


def dedupe_items(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        natural = normalize_key(item.url) or normalize_key(f"{item.source} {item.title} {item.game_name}")
        digest = hashlib.sha256(natural.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(item)
    return unique
