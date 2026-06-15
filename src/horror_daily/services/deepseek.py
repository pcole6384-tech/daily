from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from openai import OpenAI

from horror_daily.config import Settings
from horror_daily.models import NewsItem, SourceFailure

logger = logging.getLogger(__name__)


class DeepSeekSummarizer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.daily_overview = ""

    @property
    def enabled(self) -> bool:
        return bool(self.settings.deepseek_api_key)

    def enrich(self, items: list[NewsItem], failures: list[SourceFailure], report_date: date | None = None) -> list[NewsItem]:
        report_date = report_date or datetime.now(timezone.utc).date()
        if not items or not self.enabled:
            for item in items:
                self._fallback(item)
            self.daily_overview = self._fallback_overview(items)
            return items
        try:
            result = self._call(items, failures, report_date)
            self.daily_overview = _clean_text(result.get("daily_overview", "")) or self._fallback_overview(items)
            by_url = {entry.get("url"): entry for entry in result.get("items", []) if entry.get("url")}
            for item in items:
                data = by_url.get(item.url)
                if not data:
                    self._fallback(item)
                    continue
                item.ai_summary = _clean_text(data.get("summary") or item.summary[:300])
                item.recommendation_reason = _clean_text(
                    data.get("recommendation_reason") or "来源可靠且与 PC 恐怖游戏关注范围相关。"
                )
                item.preference_match = _clean_text(data.get("preference_match") or item.preference_match)
                item.risk_note = _clean_text(data.get("risk_note") or item.risk_note)
                self._guard_known_facts(item, report_date)
            return items
        except Exception as exc:
            logger.warning("DeepSeek summarization failed, using fallback summaries: %s", exc)
            for item in items:
                self._fallback(item)
            self.daily_overview = self._fallback_overview(items)
            return items

    def _call(self, items: list[NewsItem], failures: list[SourceFailure], report_date: date) -> dict:
        client = OpenAI(api_key=self.settings.deepseek_api_key, base_url=self.settings.deepseek_base_url)
        payload = [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "game_title": item.game_title or item.game_name,
                "series": item.series,
                "platform": item.platform,
                "tags": item.tags,
                "info_type": item.info_type.value,
                "section": item.section,
                "release_date": item.raw.get("release_date") if isinstance(item.raw, dict) else "",
                "release_status": _release_status(item, report_date),
                "summary": item.summary[:900],
            }
            for item in items[:40]
        ]
        prompt = (
            "你是 PC 恐怖游戏日报编辑。必须输出 JSON 对象，包含 daily_overview 和 items。"
            "daily_overview 用自然语言写一段今日恐游圈概况，尽量具体但不要结构化，不要堆太多数字。"
            "items 是数组，每项包含 url, summary, recommendation_reason, preference_match, risk_note。"
            "所有正文必须中文改写，可保留英文游戏原名；禁止输出 HTML、图片标签、长段英文原文。"
            "结构化字段 release_status 是硬事实，不得写出相反发售状态。"
            "Resident Evil Requiem 是 CAPCOM 官方 Resident Evil 正统新作，不得说成非官方或蹭名。"
            "不要编造价格、好评率或史低。价格由系统模块展示。"
        )
        response = client.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_date": report_date.isoformat(),
                            "items": payload,
                            "source_failures": [{"source": f.source, "error": f.error[:200]} for f in failures],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        content = content.strip().strip("`").removeprefix("json").strip()
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {"daily_overview": "", "items": parsed}

    def _fallback(self, item: NewsItem) -> None:
        item.ai_summary = _clean_text(item.summary[:360] or item.title)
        item.recommendation_reason = "来源可靠且与 PC 恐怖游戏关注范围相关，建议结合原始链接确认细节。"

    def _fallback_overview(self, items: list[NewsItem]) -> str:
        names = [item.game_title or item.game_name or item.title for item in items[:6]]
        if not names:
            return "今天没有抓取到足够明确的重点情报，系统仍完成了来源检查。"
        return "今天的 PC 恐怖游戏信息主要围绕 " + "、".join(names) + " 展开，重点包括折扣、更新、试玩和媒体消息。"

    def _guard_known_facts(self, item: NewsItem, report_date: date) -> None:
        if "resident evil requiem" in item.text_blob():
            for field in ("ai_summary", "risk_note", "recommendation_reason"):
                value = getattr(item, field)
                value = re.sub(r"非\s*Capcom|非CAPCOM|非官方|蹭名|山寨", "CAPCOM 官方", value, flags=re.I)
                setattr(item, field, value)
        if _release_status(item, report_date) == "已发售":
            item.ai_summary = item.ai_summary.replace("尚未发售，", "").replace("未发售，", "")
            item.risk_note = item.risk_note.replace("游戏尚未发售，", "").replace("尚未发售，", "")


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    value = re.sub(r"https?://\S+", " ", value)
    return " ".join(value.split())


def _release_status(item: NewsItem, report_date: date) -> str:
    raw_date = str(item.raw.get("release_date", "")) if isinstance(item.raw, dict) else ""
    release_date = _parse_release_date(raw_date)
    if not release_date:
        return "未知"
    return "未发售" if release_date.date() > report_date else "已发售"


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
