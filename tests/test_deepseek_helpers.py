from datetime import date, datetime, timezone

from horror_daily.models import NewsItem
from horror_daily.services.deepseek import _release_status


def test_chinese_release_date_before_report_date_is_released():
    item = NewsItem(
        title="FATAL FRAME II: Crimson Butterfly REMAKE",
        url="https://store.steampowered.com/app/3920610/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        raw={"release_date": "2026 年 3 月 11 日"},
    )

    assert _release_status(item, date(2026, 6, 15)) == "已发售"
