from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import httpx

from horror_daily.collectors.base import CollectionResult
from horror_daily.models import InfoType, NewsItem, SourceFailure
from horror_daily.services.db import Database
from horror_daily.services.http import build_client, describe_http_error
from horror_daily.services.retry import network_retry

logger = logging.getLogger(__name__)


class SteamCollector:
    SEARCH_URL = "https://store.steampowered.com/api/storesearch/?term={term}&cc={cc}&l={lang}"
    DETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&cc={cc}&l={lang}"
    NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={appid}&count={count}&maxlength=1200&format=json"

    def __init__(self, config: dict, db: Database):
        self.config = config
        runtime = config.get("runtime", {})
        self.db = db
        self.attempts = runtime.get("retry_attempts", 3)
        self.max_items = runtime.get("max_items_per_source", 30)
        self.max_steam_apps = runtime.get("max_steam_apps", 30)
        self.max_steam_priority_apps = runtime.get("max_steam_priority_apps", 24)
        self.steam_news_per_app = runtime.get("steam_news_per_app", 3)
        self.detail_batch_size = runtime.get("steam_detail_batch_size", 20)
        self.cc = runtime.get("steam_country", "CN")
        self.lang = runtime.get("steam_language", "english")

    def collect(self) -> CollectionResult:
        result = CollectionResult()
        app_terms: dict[int, str] = {}
        with build_client(self.config) as client:
            self._collect_search_terms(
                client,
                self.config.get("steam_priority_search_terms", []),
                app_terms,
                self.max_steam_priority_apps,
                result,
                source_label="Steam Priority Search",
            )
            self._collect_search_terms(
                client,
                self.config.get("steam_search_terms", []),
                app_terms,
                self.max_steam_priority_apps + self.max_steam_apps,
                result,
                source_label="Steam Search",
            )

            details = self._details_batch(client, list(app_terms))
            for appid, detail in details.items():
                if not detail:
                    continue
                result.items.extend(self._items_from_detail(appid, detail, app_terms.get(appid, "")))
                result.items.extend(self._news_items(client, appid, detail))
        return result

    def _collect_search_terms(
        self,
        client: httpx.Client,
        terms: list[str],
        app_terms: dict[int, str],
        cap: int,
        result: CollectionResult,
        source_label: str,
    ) -> None:
        for term in terms:
            if len(app_terms) >= cap:
                break
            try:
                apps = self._search(client, term)
                for app in apps[: self.max_items]:
                    if len(app_terms) >= cap:
                        break
                    appid = app.get("id")
                    if appid and appid not in app_terms:
                        app_terms[appid] = term
            except Exception as exc:
                message = describe_http_error(exc)
                logger.warning("%s failed: %s: %s", source_label, term, message)
                result.failures.append(SourceFailure(source=f"{source_label}:{term}", error=message))

    def _get_json(self, client: httpx.Client, url: str) -> dict:
        @network_retry(self.attempts)
        def do_get() -> dict:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

        return do_get()

    def _search(self, client: httpx.Client, term: str) -> list[dict]:
        url = self.SEARCH_URL.format(term=quote_plus(term), cc=self.cc, lang=self.lang)
        data = self._get_json(client, url)
        return data.get("items", [])

    def _details_batch(self, client: httpx.Client, appids: list[int]) -> dict[int, dict]:
        details: dict[int, dict] = {}
        for start in range(0, len(appids), self.detail_batch_size):
            chunk = appids[start : start + self.detail_batch_size]
            if not chunk:
                continue
            try:
                joined = ",".join(str(appid) for appid in chunk)
                data = self._get_json(client, self.DETAILS_URL.format(appid=joined, cc=self.cc, lang=self.lang))
                for appid in chunk:
                    payload = data.get(str(appid), {})
                    if payload.get("success"):
                        details[appid] = payload.get("data", {})
            except Exception as exc:
                logger.warning("Steam details batch failed: %s", describe_http_error(exc))
                if len(chunk) > 1:
                    details.update(self._details_one_by_one(client, chunk))
        return details

    def _details_one_by_one(self, client: httpx.Client, appids: list[int]) -> dict[int, dict]:
        details: dict[int, dict] = {}
        for appid in appids:
            try:
                data = self._get_json(client, self.DETAILS_URL.format(appid=appid, cc=self.cc, lang=self.lang))
                payload = data.get(str(appid), {})
                if payload.get("success"):
                    details[appid] = payload.get("data", {})
            except Exception as exc:
                logger.debug("Steam details failed for %s: %s", appid, describe_http_error(exc))
        return details

    def _news(self, client: httpx.Client, appid: int) -> list[dict]:
        data = self._get_json(client, self.NEWS_URL.format(appid=appid, count=self.steam_news_per_app))
        return data.get("appnews", {}).get("newsitems", [])

    def _items_from_detail(self, appid: int, detail: dict, term: str) -> list[NewsItem]:
        name = detail.get("name", f"Steam App {appid}")
        tags = [g.get("description", "") for g in detail.get("genres", []) if g.get("description")]
        tags += [c.get("description", "") for c in detail.get("categories", []) if c.get("description")]
        release_date = detail.get("release_date", {}).get("date", "")
        price = detail.get("price_overview") or {}
        is_free = bool(detail.get("is_free"))
        review_count = _as_int((detail.get("recommendations") or {}).get("total"))
        previous = self.db.save_price_snapshot(appid, name, price) if price else None

        item_type = InfoType.UPCOMING if detail.get("release_date", {}).get("coming_soon") else InfoType.RELEASE
        if price.get("discount_percent", 0) >= 20:
            item_type = InfoType.DISCOUNT

        common_raw = {
            "appid": appid,
            "release_date": release_date,
            "price": price,
            "is_free": is_free,
            "review_count": review_count,
            "search_term": term,
        }
        items = [
            NewsItem(
                title=f"{name} - Steam 商店信息",
                url=f"https://store.steampowered.com/app/{appid}/",
                source="Steam Store",
                published_at=datetime.now(timezone.utc),
                summary=self._summary_from_detail(detail, price, release_date, term),
                game_name=name,
                original_name=name,
                tags=tags[:12],
                info_type=item_type,
                source_reliability=95,
                raw=common_raw,
                review_count=review_count,
                item_title=f"{name} - Steam 商店信息",
                source_title=f"{name} - Steam 商店信息",
                game_title=name,
                game_title_confidence=1,
                series=self._guess_series(name),
            )
        ]

        if previous and price:
            old_final = previous.get("final_price")
            new_final = price.get("final")
            old_discount = previous.get("discount_percent") or 0
            new_discount = price.get("discount_percent") or 0
            if old_final != new_final or old_discount != new_discount:
                items.append(
                    NewsItem(
                        title=f"{name} - Steam 价格/折扣变化",
                        url=f"https://store.steampowered.com/app/{appid}/",
                        source="Steam Store",
                        published_at=datetime.now(timezone.utc),
                        summary=(
                            f"本次价格 {self._money(price)}；"
                            f"上次价格 {previous.get('currency')} {old_final}；"
                            f"折扣从 {old_discount}% 变为 {new_discount}%。"
                        ),
                        game_name=name,
                        original_name=name,
                        tags=[*tags[:8], "price change"],
                        info_type=InfoType.DISCOUNT,
                        source_reliability=95,
                        raw={**common_raw, "previous_price": previous},
                        review_count=review_count,
                        item_title=f"{name} - Steam 价格/折扣变化",
                        source_title=f"{name} - Steam 价格/折扣变化",
                        game_title=name,
                        game_title_confidence=1,
                        series=self._guess_series(name),
                    )
                )
        return items

    def _news_items(self, client: httpx.Client, appid: int, detail: dict) -> list[NewsItem]:
        name = detail.get("name", f"Steam App {appid}")
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.get("runtime", {}).get("days_back", 7))
        review_count = _as_int((detail.get("recommendations") or {}).get("total"))
        release_date = detail.get("release_date", {}).get("date", "")
        items: list[NewsItem] = []
        try:
            news = self._news(client, appid)
        except Exception as exc:
            logger.debug("Steam news failed for %s: %s", appid, describe_http_error(exc))
            return items
        for entry in news:
            published = datetime.fromtimestamp(entry.get("date", 0), tz=timezone.utc)
            if published < cutoff:
                continue
            title = entry.get("title", "")
            contents = " ".join((entry.get("contents") or "").replace("\n", " ").split())
            text = f"{title} {contents}".lower()
            items.append(
                NewsItem(
                    title=f"{name} - {title}",
                    url=entry.get("url") or f"https://store.steampowered.com/news/app/{appid}",
                    source="Steam News",
                    published_at=published,
                    summary=contents[:1200],
                    game_name=name,
                    original_name=name,
                    tags=self._tags_from_text(text),
                    info_type=self._guess_info_type(text),
                    source_reliability=92,
                    raw={
                        "appid": appid,
                        "gid": entry.get("gid"),
                        "release_date": release_date,
                        "is_free": bool(detail.get("is_free")),
                        "review_count": review_count,
                    },
                    review_count=review_count,
                    item_title=title,
                    source_title=title,
                    game_title=name,
                    game_title_confidence=1,
                    series=self._guess_series(name),
                )
            )
        return items

    def _summary_from_detail(self, detail: dict, price: dict, release_date: str, term: str) -> str:
        short = " ".join((detail.get("short_description") or "").split())
        parts = [short]
        if release_date:
            parts.append(f"Steam 标注发售日期：{release_date}。")
        if price:
            parts.append(f"当前价格/折扣：{self._money(price)}。")
        parts.append(f"命中检索词：{term}。")
        return " ".join(parts)[:1200]

    def _money(self, price: dict) -> str:
        if not price:
            return "未知"
        final = price.get("final_formatted") or f"{price.get('currency')} {price.get('final')}"
        discount = price.get("discount_percent", 0)
        return f"{final} (-{discount}%)" if discount else final

    def _tags_from_text(self, text: str) -> list[str]:
        terms = []
        for group in ("horror", "japanese_horror", "tracked_series"):
            terms.extend(self.config.get("keywords", {}).get(group, []))
        return sorted({term for term in terms if term.lower() in text})[:12]

    def _guess_info_type(self, text: str) -> InfoType:
        for key, terms in self.config.get("keywords", {}).get("events", {}).items():
            if any(term.lower() in text for term in terms):
                return InfoType(key)
        return InfoType.UPDATE

    def _guess_series(self, text: str) -> str:
        lower = text.lower()
        for series in self.config.get("keywords", {}).get("tracked_series", []):
            if series.lower() in lower:
                return series
        return ""


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
