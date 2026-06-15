from __future__ import annotations

from datetime import datetime, timezone

from horror_daily.models import InfoType, NewsItem, ReportSection


EVENT_POINTS = {
    InfoType.RELEASE: 18,
    InfoType.UPCOMING: 16,
    InfoType.UPDATE: 12,
    InfoType.DISCOUNT: 14,
    InfoType.DEMO: 18,
    InfoType.DLC: 13,
    InfoType.EARLY_ACCESS: 15,
    InfoType.REVIEW_TREND: 11,
    InfoType.NEWS: 8,
    InfoType.QUALITY_RISK: 4,
}


class Scorer:
    def __init__(self, config: dict):
        self.config = config
        self.keywords = config.get("keywords", {})
        self.weights = config.get("weights", {})

    def score(self, item: NewsItem) -> NewsItem:
        text = item.text_blob()
        source_points = min(item.source_reliability, 100) * 0.25 * self.weights.get("source_reliability", 1)
        freshness_points = self._freshness_points(item) * self.weights.get("freshness", 1)
        pc_points = self._match_points(text, self.keywords.get("pc", []), 10) * self.weights.get("pc_relevance", 1)
        horror_points = self._match_points(text, self.keywords.get("horror", []), 18) * self.weights.get("horror_relevance", 1)
        japanese_points = self._match_points(text, self.keywords.get("japanese_horror", []), 12) * self.weights.get("japanese_horror", 1)
        series_points = self._match_points(text, self.keywords.get("tracked_series", []), 15) * self.weights.get("tracked_series", 1)
        event_points = EVENT_POINTS.get(item.info_type, 8) * self.weights.get("event_importance", 1)
        priority_points = min(item.priority_weight, 100) * 0.18 * self.weights.get("priority", 1)
        item.score = round(
            source_points
            + freshness_points
            + pc_points
            + horror_points
            + japanese_points
            + series_points
            + event_points
            + priority_points,
            2,
        )
        item.preference_match = self._preference_match(text, item)
        item.risk_note = self._risk_note(item)
        item.section = self._section(item, text)
        return item

    def _freshness_points(self, item: NewsItem) -> float:
        age_hours = max(0, (datetime.now(timezone.utc) - item.published_at).total_seconds() / 3600)
        if age_hours <= 48:
            return 18
        if age_hours <= 96:
            return 12
        if age_hours <= 168:
            return 6
        return 2

    def _match_points(self, text: str, terms: list[str], max_points: int) -> float:
        if not terms:
            return 0
        hits = len({term.lower() for term in terms if term.lower() in text})
        return min(max_points, hits * 3)

    def _preference_match(self, text: str, item: NewsItem) -> str:
        matches = []
        if item.priority_name:
            matches.append(f"优先关注：{item.priority_name}（{item.priority_tier}，命中 {item.matched_alias}）")
        for label, key in [("日式恐怖", "japanese_horror"), ("重点系列", "tracked_series"), ("恐怖题材", "horror")]:
            hits = [term for term in self.keywords.get(key, []) if term.lower() in text]
            if hits:
                matches.append(f"{label}: {', '.join(hits[:4])}")
        return "；".join(matches) if matches else "一般匹配：PC 恐怖游戏相关信息"

    def _risk_note(self, item: NewsItem) -> str:
        notes = []
        if item.source_reliability < 70:
            notes.append("来源可信度中等，需要等待官方确认")
        if len(item.summary) < 80:
            notes.append("公开信息较少，判断空间有限")
        if item.review_gate_result.startswith("blocked"):
            notes.append("Steam 评测人数未达到正式日报门槛")
        return "；".join(notes) if notes else "暂无明显风险；仍建议查看原始链接确认平台、版本和发售状态"

    def _section(self, item: NewsItem, text: str) -> str:
        suspicious_threshold = self.config.get("runtime", {}).get("suspicious_score_below", 35)
        must_threshold = self.config.get("runtime", {}).get("min_score_for_must_read", 70)
        if item.score < suspicious_threshold or item.source_reliability < 65:
            return ReportSection.RISKS.value
        if item.score >= must_threshold:
            return ReportSection.MUST_READ.value
        if any(term.lower() in text for term in self.keywords.get("japanese_horror", [])):
            return ReportSection.JAPANESE.value
        mapping = {
            InfoType.RELEASE: ReportSection.NEW_RELEASES.value,
            InfoType.UPCOMING: ReportSection.UPCOMING.value,
            InfoType.UPDATE: ReportSection.UPDATES.value,
            InfoType.DISCOUNT: ReportSection.DISCOUNTS.value,
            InfoType.DEMO: ReportSection.DEMOS.value,
            InfoType.DLC: ReportSection.UPDATES.value,
            InfoType.EARLY_ACCESS: ReportSection.UPCOMING.value,
            InfoType.REVIEW_TREND: ReportSection.REVIEW_TRENDS.value,
        }
        return mapping.get(item.info_type, ReportSection.WATCHLIST.value)
