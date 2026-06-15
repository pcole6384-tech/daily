from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class InfoType(str, Enum):
    RELEASE = "release"
    UPCOMING = "upcoming"
    UPDATE = "update"
    DISCOUNT = "discount"
    DEMO = "demo"
    DLC = "dlc"
    EARLY_ACCESS = "early_access"
    REVIEW_TREND = "review_trend"
    NEWS = "news"
    QUALITY_RISK = "quality_risk"


class ReportSection(str, Enum):
    MUST_READ = "今日必看"
    NEW_RELEASES = "新发布恐怖游戏"
    UPCOMING = "即将发售/新曝光"
    UPDATES = "重要更新"
    DISCOUNTS = "折扣与价格变动"
    DEMOS = "Demo/试玩/节日活动"
    JAPANESE = "日式恐怖重点关注"
    REVIEW_TRENDS = "评价趋势变化"
    RISKS = "避雷/质量存疑"
    WATCHLIST = "今日推荐关注清单"


@dataclass(slots=True)
class PriceOffer:
    game_name: str
    store: str
    store_type: str
    price: float | None
    currency: str
    regular_price: float | None = None
    discount_percent: int = 0
    drm: str = ""
    region: str = ""
    url: str = ""
    source: str = ""
    price_clear: bool = False
    region_ok: bool = False
    product_clear: bool = False
    recommended: bool = False
    historical_low: str = "未知"
    note: str = ""
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class SourceFailure:
    source: str
    error: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class NewsItem:
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str = ""
    game_name: str = ""
    original_name: str = ""
    platform: str = "PC"
    tags: list[str] = field(default_factory=list)
    info_type: InfoType = InfoType.NEWS
    source_reliability: int = 70
    raw: dict[str, Any] = field(default_factory=dict)
    score: float = 0
    section: str = ""
    ai_summary: str = ""
    recommendation_reason: str = ""
    preference_match: str = ""
    risk_note: str = ""
    price_offers: list[PriceOffer] = field(default_factory=list)
    item_title: str = ""
    game_title: str = ""
    source_title: str = ""
    series: str = ""
    game_title_confidence: float = 0
    recommendation_action: str = ""
    validation_notes: list[str] = field(default_factory=list)
    priority_name: str = ""
    priority_tier: str = ""
    priority_weight: int = 0
    matched_alias: str = ""
    review_count: int | None = None
    review_gate_result: str = ""
    inclusion_reason: str = ""
    excluded_from_readable: bool = False

    @property
    def dedupe_key(self) -> str:
        basis = self.url.strip().lower() or f"{self.source}:{self.title}:{self.game_name}"
        return basis[:500]

    @property
    def display_name(self) -> str:
        return self.game_title or self.game_name or self.original_name or self.title

    def text_blob(self) -> str:
        return " ".join(
            [
                self.title or "",
                self.summary or "",
                self.game_title or "",
                self.game_name or "",
                self.original_name or "",
                self.item_title or "",
                self.source_title or "",
                self.series or "",
                " ".join(self.tags),
            ]
        ).lower()
