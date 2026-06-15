from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from horror_daily.models import NewsItem


@dataclass(frozen=True)
class PriorityEntry:
    tier: str
    name: str
    aliases: tuple[str, ...]
    weight: int


MOJIBAKE_MARKERS = ("�", "鏉", "绾", "鎭", "鍙", "闆", "蹇", "锛", "銆")


def load_priority_config(path: str | Path = "config/priority.yaml") -> dict[str, Any]:
    priority_path = Path(path)
    if not priority_path.exists():
        return {"priority_search_terms": {}}
    with priority_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {"priority_search_terms": {}}


def flatten_priority_entries(priority_config: dict[str, Any]) -> list[PriorityEntry]:
    groups = priority_config.get("priority_search_terms", {}) or {}
    entries: list[PriorityEntry] = []
    for tier, raw_entries in groups.items():
        for raw in raw_entries or []:
            name = str(raw.get("name", "")).strip()
            aliases = [name, *(raw.get("aliases") or [])]
            clean_aliases = tuple(_dedupe(alias for alias in aliases if _usable_alias(str(alias))))
            if not name or not clean_aliases:
                continue
            entries.append(
                PriorityEntry(
                    tier=str(tier),
                    name=name,
                    aliases=clean_aliases,
                    weight=int(raw.get("weight") or 0),
                )
            )
    return entries


def apply_priority(items: list[NewsItem], priority_config: dict[str, Any]) -> list[NewsItem]:
    matcher = PriorityMatcher(priority_config)
    for item in items:
        matcher.apply(item)
    return items


def priority_aliases_for_steam(priority_config: dict[str, Any], min_weight: int = 50) -> list[str]:
    aliases: list[str] = []
    for entry in flatten_priority_entries(priority_config):
        if entry.weight < min_weight:
            continue
        aliases.extend(entry.aliases)
    return list(_dedupe(aliases))


class PriorityMatcher:
    def __init__(self, priority_config: dict[str, Any]):
        self.entries = flatten_priority_entries(priority_config)

    def apply(self, item: NewsItem) -> NewsItem:
        match = self.match(item)
        if not match:
            return item
        entry, alias = match
        item.priority_name = entry.name
        item.priority_tier = entry.tier
        item.priority_weight = entry.weight
        item.matched_alias = alias
        if not item.series:
            item.series = entry.name
        return item

    def match(self, item: NewsItem) -> tuple[PriorityEntry, str] | None:
        text = _normalize_text(
            " ".join(
                [
                    item.title,
                    item.summary,
                    item.game_title,
                    item.game_name,
                    item.original_name,
                    item.item_title,
                    item.source_title,
                    item.series,
                    " ".join(item.tags),
                ]
            )
        )
        best: tuple[PriorityEntry, str] | None = None
        best_rank: tuple[int, int] = (-1, -1)
        for entry in self.entries:
            for alias in entry.aliases:
                normalized_alias = _normalize_text(alias)
                if not normalized_alias:
                    continue
                if _contains_alias(text, normalized_alias):
                    rank = (entry.weight, len(normalized_alias))
                    if rank > best_rank:
                        best = (entry, alias)
                        best_rank = rank
        return best


def _contains_alias(text: str, alias: str) -> bool:
    if re.fullmatch(r"[a-z0-9 ]+", alias):
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text) is not None
    return alias in text


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _usable_alias(value: str) -> bool:
    alias = value.strip()
    if not alias:
        return False
    if any(marker in alias for marker in MOJIBAKE_MARKERS):
        return False
    return True


def _dedupe(values) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = str(value).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
    return tuple(output)
