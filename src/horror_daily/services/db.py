from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from horror_daily.models import NewsItem, PriceOffer, SourceFailure


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                published_at TEXT NOT NULL,
                summary TEXT,
                game_name TEXT,
                original_name TEXT,
                platform TEXT,
                tags_json TEXT NOT NULL,
                info_type TEXT NOT NULL,
                source_reliability INTEGER NOT NULL,
                score REAL NOT NULL,
                section TEXT,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                error TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appid INTEGER NOT NULL,
                name TEXT NOT NULL,
                currency TEXT,
                initial_price INTEGER,
                final_price INTEGER,
                discount_percent INTEGER,
                captured_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                markdown_path TEXT NOT NULL,
                html_path TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_name TEXT NOT NULL,
                store TEXT NOT NULL,
                store_type TEXT NOT NULL,
                price REAL,
                currency TEXT NOT NULL,
                regular_price REAL,
                discount_percent INTEGER NOT NULL DEFAULT 0,
                drm TEXT,
                region TEXT,
                url TEXT,
                source TEXT NOT NULL,
                price_clear INTEGER NOT NULL DEFAULT 0,
                region_ok INTEGER NOT NULL DEFAULT 0,
                product_clear INTEGER NOT NULL DEFAULT 0,
                recommended INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                captured_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, message: str = "") -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, message = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), status, message, run_id),
        )
        self.conn.commit()

    def save_items(self, items: Iterable[NewsItem]) -> list[NewsItem]:
        saved: list[NewsItem] = []
        for item in items:
            try:
                self.conn.execute(
                    """
                    INSERT INTO items (
                        dedupe_key, title, url, source, published_at, summary,
                        game_name, original_name, platform, tags_json, info_type,
                        source_reliability, score, section, raw_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.dedupe_key,
                        item.title,
                        item.url,
                        item.source,
                        item.published_at.isoformat(),
                        item.summary,
                        item.game_name,
                        item.original_name,
                        item.platform,
                        json.dumps(item.tags, ensure_ascii=False),
                        item.info_type.value,
                        item.source_reliability,
                        item.score,
                        item.section,
                        json.dumps(item.raw, ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                saved.append(item)
            except sqlite3.IntegrityError:
                continue
        self.conn.commit()
        return saved

    def save_failures(self, failures: Iterable[SourceFailure]) -> None:
        self.conn.executemany(
            "INSERT INTO source_failures (source, error, occurred_at) VALUES (?, ?, ?)",
            [(f.source, f.error[:1000], f.occurred_at.isoformat()) for f in failures],
        )
        self.conn.commit()

    def save_price_snapshot(self, appid: int, name: str, price: dict) -> dict | None:
        latest = self.conn.execute(
            "SELECT * FROM price_snapshots WHERE appid = ? ORDER BY captured_at DESC LIMIT 1",
            (appid,),
        ).fetchone()
        snapshot = {
            "currency": price.get("currency"),
            "initial_price": price.get("initial"),
            "final_price": price.get("final"),
            "discount_percent": price.get("discount_percent", 0),
        }
        self.conn.execute(
            """
            INSERT INTO price_snapshots
            (appid, name, currency, initial_price, final_price, discount_percent, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                appid,
                name,
                snapshot["currency"],
                snapshot["initial_price"],
                snapshot["final_price"],
                snapshot["discount_percent"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return dict(latest) if latest else None

    def save_report(self, report_date: str, markdown_path: Path, html_path: Path, sent: bool) -> None:
        self.conn.execute(
            "INSERT INTO reports (report_date, markdown_path, html_path, sent, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                report_date,
                str(markdown_path),
                str(html_path),
                int(sent),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def save_price_offers(self, offers: Iterable[PriceOffer]) -> None:
        self.conn.executemany(
            """
            INSERT INTO price_offers (
                game_name, store, store_type, price, currency, regular_price,
                discount_percent, drm, region, url, source, price_clear,
                region_ok, product_clear, recommended, note, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    offer.game_name,
                    offer.store,
                    offer.store_type,
                    offer.price,
                    offer.currency,
                    offer.regular_price,
                    offer.discount_percent,
                    offer.drm,
                    offer.region,
                    offer.url,
                    offer.source,
                    int(offer.price_clear),
                    int(offer.region_ok),
                    int(offer.product_clear),
                    int(offer.recommended),
                    offer.note,
                    offer.captured_at.isoformat(),
                )
                for offer in offers
            ],
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
