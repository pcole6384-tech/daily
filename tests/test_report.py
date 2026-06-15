import json
from datetime import date, datetime, timezone

from horror_daily.models import InfoType, NewsItem, ReportSection
from horror_daily.pipeline.report import ReportRenderer


def test_report_renderer_writes_readable_and_debug_outputs(tmp_path):
    visible = NewsItem(
        title="Test Horror",
        url="https://example.com",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        summary="A test horror game.",
        game_name="Test Horror",
        game_title="Test Horror",
        game_title_confidence=1,
        item_title="Test Horror - Steam 商店信息",
        source_title="Test Horror - Steam 商店信息",
        tags=["horror", "steam"],
        info_type=InfoType.RELEASE,
        source_reliability=95,
        score=80,
        section=ReportSection.MUST_READ.value,
        raw={"appid": 1, "review_count": 200},
        ai_summary="<p>测试摘要</p>",
        recommendation_reason="测试理由",
        preference_match="恐怖题材",
        risk_note="暂无明显风险",
        recommendation_action="加愿望单",
        review_count=200,
        review_gate_result="passed: review_count 200 >= 200",
    )
    hidden = NewsItem(
        title="Hidden Horror",
        url="https://example.com/hidden",
        source="Steam Store",
        published_at=datetime.now(timezone.utc),
        summary="Hidden.",
        game_title="Hidden Horror",
        game_title_confidence=1,
        info_type=InfoType.DISCOUNT,
        score=60,
        section=ReportSection.DISCOUNTS.value,
        excluded_from_readable=True,
        review_gate_result="blocked: review_count 10 < 200",
    )

    md_path, html_path, md, html = ReportRenderer(tmp_path, {}).render(date(2026, 6, 14), [visible, hidden], [])

    assert md_path.exists()
    assert html_path.exists()
    assert (tmp_path / "readable_report.md").exists()
    assert (tmp_path / "debug_report.md").exists()
    assert (tmp_path / "debug.json").exists()
    assert "一句话判断" in md
    assert "英文原名" not in md
    assert "综合评分" not in md
    assert "测试摘要" in html
    assert "<p>测试摘要</p>" not in md
    assert "Hidden Horror" not in md

    debug = json.loads((tmp_path / "debug.json").read_text(encoding="utf-8"))
    assert any(item["title"] == "Hidden Horror" for item in debug["items"])
