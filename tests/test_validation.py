from datetime import datetime, timezone

from horror_daily.models import InfoType, NewsItem, ReportSection
from horror_daily.pipeline.validation import validate_report_items


CONFIG = {
    "runtime": {"min_review_count_for_released": 200},
    "keywords": {
        "horror": ["horror"],
        "tracked_series": ["resident evil", "silent hill", "fatal frame"],
    },
}


def test_article_title_is_not_used_as_game_title():
    item = NewsItem(
        title="Resident Evil Veronica Will Use a Third-Person View, Confirms Capcom",
        url="https://example.com/news",
        source="GameSpot News",
        published_at=datetime.now(timezone.utc),
        summary="Capcom confirms a third-person view for the remake.",
        game_title="Resident Evil Veronica Will Use a Third-Person View, Confirms Capcom",
        game_title_confidence=0.2,
        score=80,
        section=ReportSection.MUST_READ.value,
    )

    validated = validate_report_items([item], CONFIG)[0]

    assert validated.game_title == ""
    assert validated.section == ReportSection.RISKS.value
    assert any("游戏名未可靠识别" in note for note in validated.validation_notes)


def test_demo_is_not_treated_as_release():
    item = NewsItem(
        title="CRTX - A Psychological Horror Puzzle Demo",
        url="https://store.steampowered.com/app/1/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        summary="A horror demo is available on Steam.",
        tags=["Game demo", "horror"],
        game_title="CRTX - A Psychological Horror Puzzle Demo",
        game_title_confidence=1,
        info_type=InfoType.RELEASE,
        score=75,
        section=ReportSection.NEW_RELEASES.value,
    )

    validated = validate_report_items([item], CONFIG)[0]

    assert validated.info_type == InfoType.DEMO
    assert validated.section == ReportSection.DEMOS.value
    assert validated.recommendation_action == "等正式版"
    assert validated.review_gate_result.startswith("exempt")


def test_future_discount_is_not_blocked_by_review_gate():
    item = NewsItem(
        title="FATAL FRAME II: Crimson Butterfly REMAKE - Steam 商店信息",
        url="https://store.steampowered.com/app/3920610/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        summary="Fatal Frame horror preorder discount.",
        tags=["horror"],
        game_title="FATAL FRAME II: Crimson Butterfly REMAKE",
        game_title_confidence=1,
        info_type=InfoType.DISCOUNT,
        score=80,
        section=ReportSection.MUST_READ.value,
        raw={"release_date": "2027 年 3 月 11 日", "price": {"discount_percent": 25}},
    )

    validated = validate_report_items([item], CONFIG)[0]

    assert not validated.excluded_from_readable
    assert validated.recommendation_action == "等正式版"
    assert validated.review_gate_result.startswith("exempt")


def test_released_steam_game_below_review_gate_is_excluded():
    item = NewsItem(
        title="Small Horror - Steam 商店信息",
        url="https://store.steampowered.com/app/2/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        summary="A horror game has a sale.",
        tags=["horror"],
        game_title="Small Horror",
        game_title_confidence=1,
        info_type=InfoType.DISCOUNT,
        score=70,
        section=ReportSection.DISCOUNTS.value,
        raw={"release_date": "Jun 1, 2025", "review_count": 199, "price": {"discount_percent": 50}},
        review_count=199,
    )

    validated = validate_report_items([item], CONFIG)[0]

    assert validated.excluded_from_readable
    assert validated.review_gate_result == "blocked: review_count 199 < 200"


def test_released_steam_game_at_review_gate_can_enter():
    item = NewsItem(
        title="Known Horror - Steam 商店信息",
        url="https://store.steampowered.com/app/3/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        summary="A horror game has a sale.",
        tags=["horror"],
        game_title="Known Horror",
        game_title_confidence=1,
        info_type=InfoType.DISCOUNT,
        score=70,
        section=ReportSection.DISCOUNTS.value,
        raw={"release_date": "Jun 1, 2025", "review_count": 200, "price": {"discount_percent": 50}},
        review_count=200,
    )

    validated = validate_report_items([item], CONFIG)[0]

    assert not validated.excluded_from_readable
    assert validated.review_gate_result == "passed: review_count 200 >= 200"
