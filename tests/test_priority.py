from datetime import datetime, timezone

from horror_daily.models import NewsItem
from horror_daily.pipeline.priority import PriorityMatcher, load_priority_config, priority_aliases_for_steam


def test_priority_matcher_detects_fatal_frame_alias():
    priority = load_priority_config("config/priority.yaml")
    item = NewsItem(
        title="FATAL FRAME II: Crimson Butterfly REMAKE - Steam 商店信息",
        url="https://store.steampowered.com/app/3920610/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        summary="A Japanese horror remake.",
        game_title="FATAL FRAME II: Crimson Butterfly REMAKE",
    )

    matched = PriorityMatcher(priority).apply(item)

    assert matched.priority_name == "Fatal Frame"
    assert matched.priority_tier == "tier_s"
    assert matched.priority_weight == 100
    assert matched.matched_alias


def test_priority_aliases_feed_steam_search_terms():
    priority = load_priority_config("config/priority.yaml")
    terms = priority_aliases_for_steam(priority)

    assert "Project Zero" in terms
    assert "Crimson Butterfly" in terms
    assert "FATAL FRAME II" in terms
