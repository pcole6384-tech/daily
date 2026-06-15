from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from horror_daily.models import InfoType, NewsItem, ReportSection


def validate_report_items(items: list[NewsItem], config: dict) -> list[NewsItem]:
    keywords = config.get("keywords", {})
    min_reviews = int(config.get("runtime", {}).get("min_review_count_for_released", 200))
    for item in items:
        _normalize_titles(item, keywords)
        _fix_event_type(item)
        _validate_relevance(item, keywords)
        _validate_prices(item)
        _avoid_old_store_page(item)
        _apply_review_gate(item, min_reviews)
        _apply_event_gate(item)
        item.recommendation_action = _recommend_action(item)
        item.risk_note = _fix_known_fact_errors(item.risk_note, item)
        item.ai_summary = _fix_known_fact_errors(item.ai_summary, item)
        if not item.inclusion_reason:
            item.inclusion_reason = _inclusion_reason(item)
    return items


def _normalize_titles(item: NewsItem, keywords: dict) -> None:
    item.item_title = item.item_title or item.title
    item.source_title = item.source_title or item.title
    if item.source in {"Steam Store", "Steam News"}:
        item.game_title = item.game_title or item.game_name or item.original_name
        item.game_title_confidence = max(item.game_title_confidence, 1)
    elif item.game_title_confidence < 0.6 or _looks_like_article_title(item.game_title):
        item.game_title = ""
        item.game_name = ""
        item.original_name = ""
        item.section = ReportSection.RISKS.value
        item.score = min(item.score, 45)
        _add_note(item, "游戏名未可靠识别，未把新闻标题当作游戏名。")

    if "resident evil requiem" in item.text_blob():
        item.series = "Resident Evil"
        item.game_title = item.game_title or "Resident Evil Requiem"
        item.game_title_confidence = max(item.game_title_confidence, 0.9)

    if not item.series:
        blob = item.text_blob()
        for series in keywords.get("tracked_series", []):
            if series.lower() in blob:
                item.series = series
                break


def _fix_event_type(item: NewsItem) -> None:
    blob = item.text_blob()
    if "demo" in blob or "试玩" in blob or "Game demo" in item.tags:
        item.info_type = InfoType.DEMO
        if item.section == ReportSection.NEW_RELEASES.value:
            item.section = ReportSection.DEMOS.value
        _add_note(item, "Demo/试玩内容不按正式 release 展示。")


def _validate_relevance(item: NewsItem, keywords: dict) -> None:
    blob = item.text_blob()
    horror_hit = any(term.lower() in blob for term in keywords.get("horror", []))
    series_hit = any(term.lower() in blob for term in keywords.get("tracked_series", []))
    priority_hit = bool(item.priority_name)
    if not (horror_hit or series_hit or priority_hit):
        item.section = ReportSection.RISKS.value
        item.score = min(item.score, 30)
        item.excluded_from_readable = True
        _add_note(item, "恐怖相关性不足，仅保留在 debug。")


def _validate_prices(item: NewsItem) -> None:
    valid = []
    for offer in item.price_offers:
        if offer.region.upper() != "CN" or offer.currency.upper() != "CNY":
            _add_note(item, f"已隐藏非国区价格：{offer.store}")
            continue
        if offer.price == 0 and offer.discount_percent < 100 and "free" not in offer.note.lower():
            _add_note(item, f"已隐藏需确认的 0 元价格：{offer.store}")
            continue
        if not (offer.price_clear and offer.product_clear and offer.url and not _is_search_url(offer.url)):
            _add_note(item, f"已隐藏不完整价格：{offer.store}")
            continue
        valid.append(offer)
    item.price_offers = valid


def _avoid_old_store_page(item: NewsItem) -> None:
    if item.source != "Steam Store" or item.info_type != InfoType.RELEASE:
        return
    release_date = _parse_release_date(str(item.raw.get("release_date", "")) if isinstance(item.raw, dict) else "")
    if release_date and (datetime.now(timezone.utc) - release_date).days > 30:
        item.excluded_from_readable = True
        item.inclusion_reason = "excluded: old Steam store page without recent event"
        _add_note(item, "旧商店页没有近期事件，不进入 readable。")


def _apply_review_gate(item: NewsItem, min_reviews: int) -> None:
    review_count = item.review_count
    if review_count is None and isinstance(item.raw, dict):
        review_count = _as_int(item.raw.get("review_count"))
        item.review_count = review_count
    if not _is_released_steam_store_game(item):
        item.review_gate_result = _review_exemption_reason(item)
        return
    if review_count is None:
        item.review_gate_result = f"blocked: missing review_count, threshold {min_reviews}"
        item.excluded_from_readable = True
        return
    if review_count < min_reviews:
        item.review_gate_result = f"blocked: review_count {review_count} < {min_reviews}"
        item.excluded_from_readable = True
        return
    item.review_gate_result = f"passed: review_count {review_count} >= {min_reviews}"


def _apply_event_gate(item: NewsItem) -> None:
    if item.excluded_from_readable or item.source != "Steam Store":
        return
    if item.info_type in {InfoType.DISCOUNT, InfoType.UPCOMING, InfoType.DEMO, InfoType.EARLY_ACCESS, InfoType.DLC}:
        return
    release_date = _parse_release_date(str(item.raw.get("release_date", "")) if isinstance(item.raw, dict) else "")
    if release_date and abs((datetime.now(timezone.utc) - release_date).days) <= 30:
        return
    item.excluded_from_readable = True
    item.inclusion_reason = "excluded: no recent actionable Steam event"


def _recommend_action(item: NewsItem) -> str:
    if item.excluded_from_readable:
        return "暂时观望" if item.score >= 30 else "不建议碰"
    if item.section == ReportSection.RISKS.value:
        return "暂时观望" if item.score >= 30 else "不建议碰"
    if item.info_type == InfoType.DEMO:
        return "等正式版"
    if _is_future_release(item):
        return "等正式版"
    if item.info_type in {InfoType.UPCOMING, InfoType.EARLY_ACCESS}:
        return "加愿望单"
    best_discount = max((offer.discount_percent for offer in item.price_offers), default=_steam_discount(item))
    if item.info_type == InfoType.DISCOUNT or best_discount >= 50:
        return "现在买" if best_discount >= 50 else "等折扣"
    if item.info_type == InfoType.RELEASE:
        return "加愿望单" if not item.price_offers else "等折扣"
    return "暂时观望"


def _inclusion_reason(item: NewsItem) -> str:
    if item.excluded_from_readable:
        return "excluded"
    if item.info_type == InfoType.DISCOUNT:
        return "included: discount or price change"
    if item.info_type == InfoType.UPCOMING:
        return "included: upcoming information"
    if item.info_type == InfoType.DEMO:
        return "included: demo information"
    if item.source != "Steam Store":
        return "included: authoritative news/feed item"
    return "included: recent Steam item"


def _review_exemption_reason(item: NewsItem) -> str:
    if _is_future_release(item):
        return "exempt: unreleased item"
    if item.info_type in {InfoType.UPCOMING, InfoType.DEMO, InfoType.EARLY_ACCESS, InfoType.DLC}:
        return "exempt: demo/upcoming/DLC item"
    if item.source == "Steam News":
        return "exempt: Steam News event"
    if item.priority_tier == "tier_s" and item.source != "Steam Store":
        return "exempt: S-tier authoritative news"
    return "not_applicable"


def _is_released_steam_store_game(item: NewsItem) -> bool:
    if item.source != "Steam Store":
        return False
    if item.info_type in {InfoType.UPCOMING, InfoType.DEMO, InfoType.EARLY_ACCESS, InfoType.DLC}:
        return False
    return not _is_future_release(item) and item.info_type in {InfoType.RELEASE, InfoType.DISCOUNT}


def _parse_release_date(value: str) -> datetime | None:
    if not value or value.lower() in {"coming soon", "to be announced", "tba"}:
        return None
    for fmt in ("%b %d, %Y", "%d %b, %Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", value)
    if match:
        year, month, day = map(int, match.groups())
        return datetime(year, month, day, tzinfo=timezone.utc)
    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _is_future_release(item: NewsItem) -> bool:
    if not isinstance(item.raw, dict):
        return False
    release_date = _parse_release_date(str(item.raw.get("release_date", "")))
    return bool(release_date and release_date > datetime.now(timezone.utc))


def _fix_known_fact_errors(text: str, item: NewsItem) -> str:
    if not text:
        return text
    if "resident evil requiem" in item.text_blob():
        text = re.sub(r"非\s*Capcom|非CAPCOM|非官方|蹭名|山寨", "CAPCOM 官方", text, flags=re.I)
    if not _is_future_release(item):
        text = text.replace("游戏尚未发售，", "")
        text = text.replace("尚未发售，", "")
        text = text.replace("未发售，", "")
    return text


def _looks_like_article_title(value: str) -> bool:
    if not value:
        return True
    words = value.split()
    bad_words = {"announced", "revealed", "reportedly", "confirms", "everything", "during", "why", "will", "joins"}
    return len(words) > 8 or any(word.lower().strip(",:") in bad_words for word in words)


def _is_search_url(url: str) -> bool:
    lower = url.lower()
    return "search?" in lower or "/search" in lower


def _steam_discount(item: NewsItem) -> int:
    price = item.raw.get("price") if isinstance(item.raw, dict) else {}
    return int(price.get("discount_percent") or 0) if isinstance(price, dict) else 0


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _add_note(item: NewsItem, note: str) -> None:
    if note not in item.validation_notes:
        item.validation_notes.append(note)
