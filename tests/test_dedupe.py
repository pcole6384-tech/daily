from datetime import datetime, timezone

from horror_daily.models import NewsItem
from horror_daily.pipeline.dedupe import dedupe_items


def test_dedupe_by_url():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(title="A", url="https://example.com/game?utm=1", source="x", published_at=now),
        NewsItem(title="A copy", url="https://example.com/game?utm=2", source="x", published_at=now),
    ]

    assert len(dedupe_items(items)) == 1
