from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from horror_daily.collectors.rss import RssCollector
from horror_daily.collectors.steam import SteamCollector
from horror_daily.config import get_settings, load_yaml_config
from horror_daily.pipeline.dedupe import dedupe_items
from horror_daily.pipeline.priority import apply_priority, load_priority_config, priority_aliases_for_steam
from horror_daily.pipeline.report import ReportRenderer
from horror_daily.pipeline.scoring import Scorer
from horror_daily.pipeline.validation import validate_report_items
from horror_daily.services.db import Database
from horror_daily.services.deepseek import DeepSeekSummarizer
from horror_daily.services.http import build_client, diagnose_url
from horror_daily.services.logging import configure_logging
from horror_daily.services.mailer import Mailer
from horror_daily.services.prices import PriceAggregator

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PC horror game daily intelligence automation")
    parser.add_argument("--dry-run", action="store_true", help="Collect and render report without sending email")
    parser.add_argument("--no-email", action="store_true", help="Do not send email")
    parser.add_argument("--send-test-email", action="store_true", help="Send a SMTP test email and exit")
    parser.add_argument("--doctor", action="store_true", help="Run network diagnostics and exit")
    parser.add_argument("--config", default=None, help="Path to YAML config")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    config = load_yaml_config(args.config)
    priority_config = load_priority_config()
    _merge_priority_terms(config, priority_config)

    if args.doctor:
        run_doctor(config)
        return

    mailer = Mailer(settings)
    if args.send_test_email:
        sent = mailer.send_test(dry_run=args.dry_run)
        logger.info("SMTP test %s", "sent" if sent else "not sent")
        return

    db = Database(settings.database_path)
    run_id = db.start_run()
    try:
        result_items = []
        failures = []

        steam_result = SteamCollector(config, db).collect()
        result_items.extend(steam_result.items)
        failures.extend(steam_result.failures)

        rss_result = RssCollector(config).collect()
        result_items.extend(rss_result.items)
        failures.extend(rss_result.failures)

        scorer = Scorer(config)
        prioritized = apply_priority(dedupe_items(result_items), priority_config)
        scored = [scorer.score(item) for item in prioritized]
        saved = db.save_items(scored)
        db.save_failures(failures)

        price_aggregator = PriceAggregator(config, settings)
        report_items, price_offers, price_failures = price_aggregator.enrich_items(scored)
        failures.extend(price_failures)
        db.save_price_offers(price_offers)
        db.save_failures(price_failures)
        report_items = validate_report_items(report_items, config)

        report_date = datetime.now(_timezone(settings.tz)).date()
        summarizer = DeepSeekSummarizer(settings)
        enriched = summarizer.enrich(report_items, failures, report_date)
        enriched = validate_report_items(enriched, config)

        renderer = ReportRenderer(settings.report_dir, config)
        markdown_path, html_path, _, html = renderer.render(report_date, enriched, failures, summarizer.daily_overview)

        subject = f"PC恐怖游戏日报 - {report_date.isoformat()}"
        sent = False if args.no_email else mailer.send_report(subject, html, markdown_path, dry_run=args.dry_run)
        db.save_report(report_date.isoformat(), markdown_path, html_path, sent)
        db.finish_run(run_id, "success", f"items={len(enriched)}, new_items={len(saved)}, failures={len(failures)}, sent={sent}")
        logger.info("Report generated: %s and %s", markdown_path, html_path)
    except Exception as exc:
        db.finish_run(run_id, "failed", str(exc))
        logger.exception("Run failed")
        raise
    finally:
        db.close()


def _merge_priority_terms(config: dict, priority_config: dict) -> None:
    existing = config.get("steam_priority_search_terms", []) or []
    merged = []
    seen = set()
    for term in [*existing, *priority_aliases_for_steam(priority_config)]:
        value = str(term).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            merged.append(value)
    config["steam_priority_search_terms"] = merged


def _timezone(name: str):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Singapore":
            return timezone(timedelta(hours=8))
        logger.warning("Timezone %s not found; falling back to UTC", name)
        return timezone.utc


def run_doctor(config: dict) -> None:
    urls = [
        (
            "Steam search",
            "https://store.steampowered.com/api/storesearch/?term=horror&cc=CN&l=english",
        ),
        (
            "Steam details",
            "https://store.steampowered.com/api/appdetails?appids=413150&cc=CN&l=english",
        ),
        (
            "Steam news",
            "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=413150&count=1&maxlength=500&format=json",
        ),
    ]
    rss_sources = [source for source in config.get("rss_sources", []) if source.get("enabled", True)]
    urls.extend((source["name"], source["url"]) for source in rss_sources[:10])
    with build_client(config) as client:
        for name, url in urls:
            result = diagnose_url(client, name, url)
            if result.ok:
                logger.info(
                    "OK %-24s %5ss HTTP %s %s bytes",
                    result.name,
                    result.elapsed_seconds,
                    result.status_code,
                    result.bytes_read,
                )
            else:
                logger.warning("FAIL %-22s %5ss %s", result.name, result.elapsed_seconds, result.error)
