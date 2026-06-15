from datetime import datetime, timezone

from horror_daily.models import InfoType, NewsItem, ReportSection
from horror_daily.pipeline.scoring import Scorer


CONFIG = {
    "runtime": {"min_score_for_must_read": 70, "suspicious_score_below": 35},
    "weights": {
        "source_reliability": 1,
        "freshness": 1,
        "pc_relevance": 1,
        "horror_relevance": 1.3,
        "japanese_horror": 1.4,
        "tracked_series": 1.5,
        "event_importance": 1.2,
        "priority": 1,
    },
    "keywords": {
        "pc": ["pc", "steam"],
        "horror": ["horror", "psychological horror"],
        "japanese_horror": ["japanese horror", "yurei"],
        "tracked_series": ["silent hill", "resident evil"],
    },
}


def test_scores_japanese_tracked_series_highly():
    item = NewsItem(
        title="Silent Hill Japanese horror demo on Steam",
        url="https://example.com/silent-hill",
        source="Official",
        published_at=datetime.now(timezone.utc),
        summary="A new Japanese horror demo is available on PC Steam.",
        info_type=InfoType.DEMO,
        source_reliability=95,
        priority_name="Silent Hill",
        priority_tier="tier_s",
        priority_weight=100,
        matched_alias="Silent Hill",
    )

    scored = Scorer(CONFIG).score(item)

    assert scored.score >= 70
    assert scored.section == ReportSection.MUST_READ.value
    assert "日式恐怖" in scored.preference_match
    assert "优先关注" in scored.preference_match


def test_low_reliability_goes_to_risk():
    item = NewsItem(
        title="Unknown horror rumor",
        url="https://example.com/rumor",
        source="Low",
        published_at=datetime.now(timezone.utc),
        summary="short",
        info_type=InfoType.NEWS,
        source_reliability=50,
    )

    scored = Scorer(CONFIG).score(item)

    assert scored.section == ReportSection.RISKS.value
