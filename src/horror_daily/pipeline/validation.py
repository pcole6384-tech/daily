from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from horror_daily.models import InfoType, NewsItem, ReportSection


VALID_ACTIONS = {"现在买", "加愿望单", "等折扣", "等正式版", "暂时观望", "不建议碰"}


def validate_report_items(items: list[NewsItem], config: dict) -> list[NewsItem]:
    keywords = config.get("keywords", {})
    min_reviews = int(config.get("runtime", {}).get("min_review_count_for_released", 200))
    for item in items:
        _normalize_titles(item, keywords)
        _fix_event_type(item)
        _fix_addon_priority(item)
        _validate_relevance(item, keywords)
        _validate_prices(item)
        _avoid_old_store_must_read(item)
        _apply_review_gate(item, min_reviews)
        _apply_event_gate(item)
        item.recommendation_action = _recommend_action(item)
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
        _add_note(item, "游戏名未可靠识别，未把新闻标题当作游戏名。")
        item.game_title = ""
        item.game_name = ""
        item.original_name = ""
        item.section = ReportSection.RISKS.value
        item.score = min(item.score, 45)
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
        _add_note(item, "恐怖相关性不足，不能进入正式推荐区。")


def _validate_prices(item: NewsItem) -> None:
    valid = []
    for offer in item.price_offers:
        if offer.region.upper() != "CN" or offer.currency.upper() != "CNY":
            _add_note(item, f"已隐藏非国区价格：{offer.store} {offer.currency} {offer.price}")
            continue
        if offer.price == 0 and offer.discount_percent < 100 and "free" not in offer.note.lower():
            _add_note(item, f"已隐藏需确认的 0 元价格：{offer.store}")
            continue
        if not (offer.price_clear and offer.product_clear and offer.url and not _is_search_url(offer.url)):
            _add_note(item, f"已隐藏不完整价格：{offer.store}")
            continue
        valid.append(offer)
    item.price_offers = valid


def _avoid_old_store_must_read(item: NewsItem) -> None:
    if item.source != "Steam Store":
        return
    if item.section == ReportSection.MUST_READ.value and item.info_type in {InfoType.DEMO, InfoType.UPCOMING, InfoType.EARLY_ACCESS}:
        item.section = ReportSection.DEMOS.value if item.info_type == InfoType.DEMO else ReportSection.UPCOMING.value
        _add_note(item, "Steam 商店页不是近期新闻事件，已移出今日必看。")
        return
    if item.info_type != InfoType.RELEASE:
        return
    release_date = _parse_release_date(str(item.raw.get("release_date", "")) if isinstance(item.raw, dict) else "")
    if release_date and (datetime.now(timezone.utc) - release_date).days > 30:
        item.excluded_from_readable = True
        item.inclusion_reason = "excluded: old Steam store page without recent event"
        _add_note(item, "旧游戏商店页没有近期事件，不因优先级命中进入日报。")
        if item.section == ReportSection.MUST_READ.value:
            item.section = ReportSection.WATCHLIST.value


def _apply_review_gate(item: NewsItem, min_reviews: int) -> None:
    review_count = item.review_count
    if review_count is None and isinstance(item.raw, dict):
        review_count = _as_int(item.raw.get("review_count"))
        item.review_count = review_count

    if not _is_released_steam_store_game(item):
        item.review_gate_result = _review_exemption_reason(item)
        return

    if review_count is None:
        item.review_gate_result = f"blocked: Steam 已发售正式游戏缺少评测人数，门槛为 {min_reviews}"
        item.excluded_from_readable = True
        _add_note(item, f"已发售 Steam 商店游戏缺少评测人数，未进入正式日报；门槛 {min_reviews}。")
        return

    if review_count < min_reviews:
        item.review_gate_result = f"blocked: review_count {review_count} < {min_reviews}"
        item.excluded_from_readable = True
        _add_note(item, f"Steam 评测人数 {review_count}，低于正式日报门槛 {min_reviews}。")
        return

    item.review_gate_result = f"passed: review_count {review_count} >= {min_reviews}"


def _apply_event_gate(item: NewsItem) -> None:
    if item.excluded_from_readable:
        return
    if item.source != "Steam Store":
        return
    if item.info_type in {InfoType.DISCOUNT, InfoType.UPCOMING, InfoType.DEMO, InfoType.EARLY_ACCESS, InfoType.DLC}:
        return
    release_date = _parse_release_date(str(item.raw.get("release_date", "")) if isinstance(item.raw, dict) else "")
    if release_date and abs((datetime.now(timezone.utc) - release_date).days) <= 30:
        return
    item.excluded_from_readable = True
    item.inclusion_reason = "excluded: Steam store result has no recent actionable event"
    _add_note(item, "商店搜索结果没有近期发售、折扣、Demo、更新或发售日事件，已仅保留在 debug。")


def _fix_addon_priority(item: NewsItem) -> None:
    title = f"{item.title} {item.game_title}".lower()
    addon_terms = ["upgrade", "digital deluxe", "costume", "dlc", "服装", "升级包", "deluxe upgrade"]
    if any(term in title for term in addon_terms) and item.section == ReportSection.MUST_READ.value:
        item.section = ReportSection.DISCOUNTS.value if item.price_offers else ReportSection.WATCHLIST.value
        _add_note(item, "附加内容/升级包不进入今日必看，保留为价格或关注信息。")


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
    if item.info_type in {InfoType.UPDATE, InfoType.DLC, InfoType.REVIEW_TREND, InfoType.NEWS}:
        return "暂时观望"
    return "暂时观望"


def _inclusion_reason(item: NewsItem) -> str:
    if item.excluded_from_readable:
        return "excluded"
    if item.info_type == InfoType.DISCOUNT:
        return "included: discount or price change"
    if item.info_type == InfoType.UPCOMING:
        return "included: upcoming or release-date information"
    if item.info_type == InfoType.DEMO:
        return "included: demo or playtest information"
    if item.source != "Steam Store":
        return "included: authoritative news/feed item"
    return "included: recent actionable Steam store item"


def _review_exemption_reason(item: NewsItem) -> str:
    if _is_future_release(item):
        return "exempt: unreleased item"
    if item.info_type in {InfoType.UPCOMING, InfoType.DEMO, InfoType.EARLY_ACCESS, InfoType.DLC}:
        return "exempt: unreleased/demo/early-access/DLC item"
    if item.source in {"Steam News"}:
        return "exempt: Steam News event"
    if item.priority_tier == "tier_s" and item.source != "Steam Store":
        return "exempt: S-tier authoritative news"
    return "not_applicable"


def _is_released_steam_store_game(item: NewsItem) -> bool:
    if item.source != "Steam Store":
        return False
    if item.info_type in {InfoType.UPCOMING, InfoType.DEMO, InfoType.EARLY_ACCESS, InfoType.DLC}:
        return False
    if _is_future_release(item):
        return False
    return item.info_type in {InfoType.RELEASE, InfoType.DISCOUNT}


def _looks_like_article_title(value: str) -> bool:
    if not value:
        return True
    words = value.split()
    bad_words = {"announced", "revealed", "reportedly", "confirms", "everything", "during", "why", "will", "joins"}
    return len(words) > 8 or any(word.lower().strip(",:") in bad_words for word in words)


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


def _is_search_url(url: str) -> bool:
    lower = url.lower()
    return "search?" in lower or "/search" in lower


def _is_future_release(item: NewsItem) -> bool:
    if not isinstance(item.raw, dict):
        return False
    release_date = _parse_release_date(str(item.raw.get("release_date", "")))
    return bool(release_date and release_date > datetime.now(timezone.utc))


def _steam_discount(item: NewsItem) -> int:
    if not isinstance(item.raw, dict):
        return 0
    price = item.raw.get("price") or {}
    if isinstance(price, dict):
        return int(price.get("discount_percent") or 0)
    return 0


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _add_note(item: NewsItem, note: str) -> None:
    if note not in item.validation_notes:
        item.validation_notes.append(note)
