from __future__ import annotations

import logging

from horror_daily.config import Settings
from horror_daily.models import NewsItem, PriceOffer, SourceFailure
from horror_daily.services.http import build_client, describe_http_error

logger = logging.getLogger(__name__)


class PriceAggregator:
    ITAD_LOOKUP_URL = "https://api.isthereanydeal.com/games/lookup/v1"
    ITAD_PRICES_URL = "https://api.isthereanydeal.com/games/prices/v3"

    def __init__(self, config: dict, settings: Settings):
        self.config = config
        self.settings = settings
        price_cfg = config.get("price_sources", {})
        self.max_games = int(price_cfg.get("max_games_per_run", 12))
        self.authorized_shops = set(price_cfg.get("authorized_itad_shops", []))
        self.country = settings.itad_country or price_cfg.get("itad_country", "CN")

    def enrich_items(self, items: list[NewsItem]) -> tuple[list[NewsItem], list[PriceOffer], list[SourceFailure]]:
        offers = self._steam_offers(items)
        failures: list[SourceFailure] = []
        if self.settings.itad_api_key:
            try:
                offers.extend(self._itad_offers(items))
            except Exception as exc:
                message = describe_http_error(exc)
                logger.warning("ITAD price aggregation failed: %s", message)
                failures.append(SourceFailure(source="IsThereAnyDeal", error=message))
        else:
            logger.info("ITAD_API_KEY not configured; skipping authorized key-store aggregation")

        offers_by_game: dict[str, list[PriceOffer]] = {}
        for offer in offers:
            offers_by_game.setdefault(self._norm(offer.game_name), []).append(offer)
        for item in items:
            item.price_offers = sorted(
                self._dedupe_offers(offers_by_game.get(self._norm(item.display_name), [])),
                key=lambda offer: (not offer.recommended, offer.price if offer.price is not None else 999999),
            )[:5]
        return items, offers, failures

    def _dedupe_offers(self, offers: list[PriceOffer]) -> list[PriceOffer]:
        by_store: dict[str, PriceOffer] = {}
        for offer in offers:
            existing = by_store.get(offer.store)
            if not existing:
                by_store[offer.store] = offer
                continue
            if existing.source != "Steam Store" and offer.source == "Steam Store":
                by_store[offer.store] = offer
                continue
            if offer.price is not None and (existing.price is None or offer.price < existing.price):
                by_store[offer.store] = offer
        return list(by_store.values())

    def _steam_offers(self, items: list[NewsItem]) -> list[PriceOffer]:
        offers: list[PriceOffer] = []
        for item in items:
            price = item.raw.get("price") if isinstance(item.raw, dict) else None
            appid = item.raw.get("appid") if isinstance(item.raw, dict) else None
            is_free = bool(item.raw.get("is_free")) if isinstance(item.raw, dict) else False
            if not price or price.get("final") is None:
                continue
            if (price.get("currency") or "").upper() != "CNY":
                continue
            final_amount = self._amount(price.get("final"))
            discount = int(price.get("discount_percent") or 0)
            if final_amount == 0 and not is_free and discount < 100:
                continue
            offers.append(
                PriceOffer(
                    game_name=item.display_name,
                    store="Steam",
                    store_type="official_store",
                    price=final_amount,
                    regular_price=self._amount(price.get("initial")),
                    currency=price.get("currency") or "",
                    discount_percent=discount,
                    drm="Steam",
                    region="CN",
                    url=f"https://store.steampowered.com/app/{appid}/" if appid else item.url,
                    source="Steam Store",
                    price_clear=True,
                    region_ok=True,
                    product_clear=True,
                    recommended=True,
                    note="Steam 国区价格；以打开页面后的实时账号区价格为准。",
                )
            )
        return offers

    def _itad_offers(self, items: list[NewsItem]) -> list[PriceOffer]:
        candidates = self._unique_games(items)[: self.max_games]
        if not candidates:
            return []
        id_to_name: dict[str, str] = {}
        with build_client(self.config) as client:
            for item in candidates:
                params = {"key": self.settings.itad_api_key}
                appid = item.raw.get("appid") if isinstance(item.raw, dict) else None
                if appid:
                    params["appid"] = str(appid)
                else:
                    params["title"] = item.display_name
                response = client.get(self.ITAD_LOOKUP_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                game = payload.get("game") if payload.get("found") else None
                if game and game.get("id"):
                    id_to_name[game["id"]] = item.display_name

            if not id_to_name:
                return []
            params = {
                "key": self.settings.itad_api_key,
                "country": self.country,
                "deals": "false",
                "vouchers": "false",
                "capacity": "10",
            }
            response = client.post(self.ITAD_PRICES_URL, params=params, json=list(id_to_name))
            response.raise_for_status()
            return self._parse_itad_prices(response.json(), id_to_name)

    def _parse_itad_prices(self, payload: list[dict], id_to_name: dict[str, str]) -> list[PriceOffer]:
        offers: list[PriceOffer] = []
        for game in payload:
            game_name = id_to_name.get(game.get("id"), "")
            for deal in game.get("deals", []):
                shop = deal.get("shop", {})
                shop_name = shop.get("name", "")
                if self.authorized_shops and shop_name not in self.authorized_shops:
                    continue
                price = deal.get("price") or {}
                regular = deal.get("regular") or {}
                platforms = [p.get("name", "") for p in deal.get("platforms", [])]
                drms = [d.get("name", "") for d in deal.get("drm", [])]
                if platforms and "Windows" not in platforms:
                    continue
                price_clear = price.get("amount") is not None and bool(price.get("currency"))
                if (price.get("currency") or "").upper() != "CNY":
                    continue
                if price.get("amount") == 0 and int(deal.get("cut") or 0) < 100:
                    continue
                product_clear = bool(shop_name and deal.get("url") and (drms or shop_name in {"GOG", "Epic Games Store", "Steam"}))
                region_ok = self.country.upper() == "CN"
                recommended = price_clear and product_clear and region_ok
                offers.append(
                    PriceOffer(
                        game_name=game_name,
                        store=shop_name,
                        store_type=self._store_type(shop_name),
                        price=price.get("amount"),
                        regular_price=regular.get("amount"),
                        currency=price.get("currency") or "",
                        discount_percent=int(deal.get("cut") or 0),
                        drm=", ".join(drms) if drms else shop_name,
                        region=self.country.upper(),
                        url=deal.get("url", ""),
                        source="IsThereAnyDeal",
                        price_clear=price_clear,
                        region_ok=region_ok,
                        product_clear=product_clear,
                        recommended=recommended,
                        note="ITAD 按 CN 区域请求；购买前仍需打开商店页确认国区可激活和商品说明。",
                    )
                )
        return offers

    def _unique_games(self, items: list[NewsItem]) -> list[NewsItem]:
        seen: set[str] = set()
        result: list[NewsItem] = []
        for item in sorted(items, key=lambda i: i.score, reverse=True):
            raw = item.raw if isinstance(item.raw, dict) else {}
            if not raw.get("appid") and not raw.get("price_lookup"):
                continue
            key = self._norm(item.display_name)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _store_type(self, shop_name: str) -> str:
        official = {"Steam", "GOG", "Epic Games Store", "itch.io"}
        return "official_store" if shop_name in official else "authorized_key_store"

    def _amount(self, cents: int | float | None) -> float | None:
        if cents is None:
            return None
        return round(float(cents) / 100, 2)

    def _norm(self, value: str) -> str:
        return " ".join(value.lower().split())
