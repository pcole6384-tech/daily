from horror_daily.collectors.steam import SteamCollector
from horror_daily.models import InfoType


class DummyDb:
    def save_price_snapshot(self, appid, name, price):
        return None


def test_steam_detail_records_review_count():
    collector = SteamCollector({"runtime": {}, "keywords": {}}, DummyDb())
    detail = {
        "name": "Known Horror",
        "short_description": "A horror game.",
        "genres": [{"description": "Horror"}],
        "categories": [{"description": "Single-player"}],
        "release_date": {"coming_soon": False, "date": "Jun 1, 2025"},
        "price_overview": {"currency": "CNY", "initial": 1000, "final": 500, "discount_percent": 50},
        "recommendations": {"total": 250},
        "is_free": False,
    }

    item = collector._items_from_detail(123, detail, "horror")[0]

    assert item.info_type == InfoType.DISCOUNT
    assert item.review_count == 250
    assert item.raw["review_count"] == 250
