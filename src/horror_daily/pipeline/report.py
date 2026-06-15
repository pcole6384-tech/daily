from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape
from markdown import markdown

from horror_daily.models import InfoType, NewsItem, PriceOffer, ReportSection, SourceFailure


SECTION_ORDER = [section.value for section in ReportSection]


class ReportRenderer:
    def __init__(self, report_dir: Path, config: dict | None = None):
        self.report_dir = report_dir
        self.config = config or {}
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.env = Environment(
            loader=PackageLoader("horror_daily", "templates"),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=False,
            lstrip_blocks=True,
        )

    def render(
        self,
        report_date: date,
        items: list[NewsItem],
        failures: list[SourceFailure],
        daily_overview: str = "",
    ) -> tuple[Path, Path, str, str]:
        visible_items = [item for item in items if not item.excluded_from_readable]
        readable_items = [self._readable_item(item) for item in visible_items]
        grouped = self._group(readable_items)
        context = {
            "report_date": report_date.isoformat(),
            "daily_overview": daily_overview or self._fallback_overview(visible_items),
            "sections": SECTION_ORDER,
            "grouped": grouped,
            "failures": failures,
            "item_count": len(readable_items),
        }
        md = self._clean_markdown(self.env.get_template("readable_report.md.j2").render(**context))
        html_body = markdown(md, extensions=["tables"])
        html = self.env.get_template("report.html.j2").render(report_date=report_date.isoformat(), body=html_body)

        md_path = self.report_dir / f"horror-daily-{report_date.isoformat()}.md"
        html_path = self.report_dir / f"horror-daily-{report_date.isoformat()}.html"
        md_path.write_text(md, encoding="utf-8")
        html_path.write_text(html, encoding="utf-8")
        (self.report_dir / "readable_report.md").write_text(md, encoding="utf-8")
        (self.report_dir / "debug_report.md").write_text(self._debug_markdown(report_date, items, failures), encoding="utf-8")
        (self.report_dir / "debug.json").write_text(self._debug_json(items, failures), encoding="utf-8")
        return md_path, html_path, md, html

    def _group(self, items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in sorted(items, key=lambda i: i["score"], reverse=True):
            grouped[item["section"]].append(item)
        if not items:
            grouped[ReportSection.WATCHLIST.value] = []
        return grouped

    def _readable_item(self, item: NewsItem) -> dict[str, Any]:
        game_title = item.game_title if item.game_title_confidence >= 0.6 else ""
        risk_note = self._clean_editorial_text(item.risk_note or "暂无明确风险；仍建议查看原始链接。")
        if item.review_gate_result.startswith("exempt"):
            risk_note = f"{risk_note}；评测基数说明：{self._review_gate_label(item.review_gate_result)}"
        elif item.review_gate_result.startswith("passed"):
            risk_note = f"{risk_note}；Steam 评测人数已满足日报门槛。"
        return {
            "heading": game_title or item.item_title or item.title,
            "game_title": game_title or "游戏名未可靠识别",
            "series": item.series or "",
            "section": item.section or ReportSection.WATCHLIST.value,
            "score": item.score,
            "judgment": self._judgment(item, game_title),
            "what_happened": self._clean_editorial_text(item.ai_summary or item.summary or item.title),
            "why_it_matters": self._clean_editorial_text(item.recommendation_reason or "这条信息与 PC 恐怖游戏关注范围相关。"),
            "suggestion": item.recommendation_action or "暂时观望",
            "risk_note": risk_note,
            "source": item.source,
            "url": item.url,
            "prices": [self._format_price(offer) for offer in item.price_offers],
            "show_prices": item.info_type == InfoType.DISCOUNT or bool(item.price_offers),
        }

    def _judgment(self, item: NewsItem, game_title: str) -> str:
        if not game_title:
            return "信息有参考价值，但游戏名未可靠识别。"
        if item.recommendation_action == "现在买":
            return f"{game_title} 当前有明确国区报价，可以优先查看。"
        if item.recommendation_action == "等正式版":
            return f"{game_title} 适合先试玩或继续观察正式版反馈。"
        if item.recommendation_action == "加愿望单":
            return f"{game_title} 值得加入愿望单持续跟踪。"
        if item.recommendation_action == "等折扣":
            return f"{game_title} 可以关注，但不急着原价入手。"
        if item.recommendation_action == "不建议碰":
            return f"{game_title} 当前风险较高，不建议投入时间或金钱。"
        return f"{game_title} 值得先观察，不建议立刻决策。"

    def _format_price(self, offer: PriceOffer) -> dict[str, str]:
        return {
            "store": f"{offer.store} 国区",
            "price": "国区价格未获取" if offer.price is None else f"¥{offer.price:.2f}",
            "discount": f"-{offer.discount_percent}%" if offer.discount_percent else "无",
            "historical_low": offer.historical_low or "未知",
            "url": offer.url,
        }

    def _fallback_overview(self, items: list[NewsItem]) -> str:
        names = [item.game_title or item.game_name or item.title for item in items[:6]]
        if not names:
            return "今天没有抓取到足够明确的重点情报。"
        return "今天的 PC 恐怖游戏信息主要围绕 " + "、".join(names) + " 展开，重点是折扣、更新、试玩和媒体消息。"

    def _debug_markdown(self, report_date: date, items: list[NewsItem], failures: list[SourceFailure]) -> str:
        lines = [f"# Debug Report - {report_date.isoformat()}", "", f"- items: {len(items)}", f"- failures: {len(failures)}", ""]
        for item in sorted(items, key=lambda i: i.score, reverse=True):
            lines.append(f"## {item.title}")
            lines.append(f"- excluded_from_readable: {item.excluded_from_readable}")
            lines.append(f"- inclusion_reason: {item.inclusion_reason or 'N/A'}")
            lines.append(f"- game_title: {item.game_title or 'UNRELIABLE'}")
            lines.append(f"- section: {item.section}")
            lines.append(f"- score: {item.score}")
            lines.append(f"- review_count: {item.review_count if item.review_count is not None else 'N/A'}")
            lines.append(f"- review_gate_result: {item.review_gate_result or 'N/A'}")
            lines.append(f"- validation_notes: {'; '.join(item.validation_notes) if item.validation_notes else 'none'}")
            lines.append("")
        return "\n".join(lines)

    def _debug_json(self, items: list[NewsItem], failures: list[SourceFailure]) -> str:
        def default(value):
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value)

        return json.dumps({"items": [asdict(item) for item in items], "failures": [asdict(f) for f in failures]}, ensure_ascii=False, indent=2, default=default)

    def _clean_markdown(self, md: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"

    def _clean_editorial_text(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", str(text or ""))
        text = re.sub(r"https?://\S+", " ", text)
        text = " ".join(text.split())
        return text or "暂无。"

    def _review_gate_label(self, value: str) -> str:
        if "unreleased" in value or "demo" in value:
            return "未发售/Demo/DLC 不套用已发售评测人数门槛。"
        if "S-tier" in value:
            return "S 级权威新闻可先进入观察，但不代表已有足够玩家评测。"
        return "该条不适用已发售 Steam 商店评测人数门槛。"
