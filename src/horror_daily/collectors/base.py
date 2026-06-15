from __future__ import annotations

from dataclasses import dataclass, field

from horror_daily.models import NewsItem, SourceFailure


@dataclass(slots=True)
class CollectionResult:
    items: list[NewsItem] = field(default_factory=list)
    failures: list[SourceFailure] = field(default_factory=list)
