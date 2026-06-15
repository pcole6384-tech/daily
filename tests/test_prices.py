from datetime import datetime, timezone

from horror_daily.config import Settings
from horror_daily.models import NewsItem
from horror_daily.services.prices import PriceAggregator


def test_steam_price_offer_from_cn_raw_price():
    item = NewsItem(
        title="Test Horror",
        url="https://store.steampowered.com/app/1/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        game_name="Test Horror",
        game_title="Test Horror",
        raw={
            "appid": 1,
            "is_free": False,
            "price": {
                "currency": "CNY",
                "initial": 10000,
                "final": 5000,
                "discount_percent": 50,
            },
        },
    )
    config = {"runtime": {"steam_country": "CN"}, "price_sources": {}}

    items, offers, failures = PriceAggregator(config, Settings()).enrich_items([item])

    assert not failures
    assert offers[0].store == "Steam"
    assert offers[0].currency == "CNY"
    assert offers[0].region == "CN"
    assert offers[0].price == 50
    assert items[0].price_offers


def test_steam_price_offer_hides_usd_and_unconfirmed_zero():
    usd = NewsItem(
        title="USD Horror",
        url="https://store.steampowered.com/app/2/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        game_name="USD Horror",
        raw={"appid": 2, "price": {"currency": "USD", "initial": 1000, "final": 500, "discount_percent": 50}},
    )
    zero = NewsItem(
        title="Zero Horror",
        url="https://store.steampowered.com/app/3/",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        game_name="Zero Horror",
        raw={"appid": 3, "is_free": False, "price": {"currency": "CNY", "initial": 1000, "final": 0, "discount_percent": 0}},
    )

    _, offers, _ = PriceAggregator({"price_sources": {}}, Settings()).enrich_items([usd, zero])

    assert offers == []
