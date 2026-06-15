from __future__ import annotations

import json
import logging

from openai import OpenAI

from horror_daily.config import Settings
from horror_daily.models import NewsItem, SourceFailure

logger = logging.getLogger(__name__)


class DeepSeekSummarizer:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.deepseek_api_key)

    def enrich(self, items: list[NewsItem], failures: list[SourceFailure]) -> list[NewsItem]:
        if not items or not self.enabled:
            for item in items:
                self._fallback(item)
            return items
        try:
            enriched = self._call(items, failures)
            by_url = {entry.get("url"): entry for entry in enriched if entry.get("url")}
            for item in items:
                data = by_url.get(item.url)
                if not data:
                    self._fallback(item)
                    continue
                item.ai_summary = data.get("summary") or item.summary[:300]
                item.recommendation_reason = data.get("recommendation_reason") or "基于来源可信度、题材匹配和事件重要性进入日报。"
                item.preference_match = data.get("preference_match") or item.preference_match
                item.risk_note = data.get("risk_note") or item.risk_note
            return items
        except Exception as exc:
            logger.warning("DeepSeek summarization failed, using fallback summaries: %s", exc)
            for item in items:
                self._fallback(item)
            return items

    def _call(self, items: list[NewsItem], failures: list[SourceFailure]) -> list[dict]:
        client = OpenAI(
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_base_url,
        )
        payload = [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "game_name": item.game_name,
                "original_name": item.original_name,
                "platform": item.platform,
                "tags": item.tags,
                "info_type": item.info_type.value,
                "source_reliability": item.source_reliability,
                "score": item.score,
                "section": item.section,
                "raw_summary": item.summary[:900],
            }
            for item in items[:40]
        ]
        failure_payload = [{"source": f.source, "error": f.error[:200]} for f in failures]
        prompt = (
            "你是 PC 恐怖游戏情报编辑。请把输入条目改写为中文日报可用字段。"
            "要求：中文为主，保留英文原名；数据化、清晰、可执行；不要营销腔；"
            "明确区分事实、推测和推荐；低可信或信息不足时标注不确定。"
            "不要在 summary/recommendation_reason 中编造价格、好评率或发售状态；"
            "如果输入中出现外区价格或美元价格，不要复述，价格只由系统的国区价格模块展示。"
            "只输出 JSON 数组，每项包含 url, summary, recommendation_reason, preference_match, risk_note。"
        )
        response = client.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"items": payload, "source_failures": failure_payload},
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or "[]"
        return json.loads(content.strip().strip("`").removeprefix("json").strip())

    def _fallback(self, item: NewsItem) -> None:
        item.ai_summary = item.summary[:360] or item.title
        item.recommendation_reason = "基于官方/权威来源、PC 相关性、恐怖题材匹配和事件类型进入本期观察。"
