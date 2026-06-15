from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from horror_daily.config import Settings

logger = logging.getLogger(__name__)


class Mailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.mail_from and self.settings.mail_to)

    def send_report(self, subject: str, html: str, markdown_path: Path, dry_run: bool = False) -> bool:
        if dry_run:
            logger.info("Dry-run mail: %s -> %s", subject, self.settings.mail_to or "(not configured)")
            return False
        if not self.configured:
            logger.warning("SMTP not configured; report generated but not sent")
            return False

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.settings.mail_from
        msg["To"] = self.settings.mail_to
        msg.set_content("请查看 HTML 日报；Markdown 附件也已随信附上。")
        msg.add_alternative(html, subtype="html")
        if markdown_path.exists():
            msg.add_attachment(
                markdown_path.read_bytes(),
                maintype="text",
                subtype="markdown",
                filename=markdown_path.name,
            )

        if self.settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(self.settings.smtp_host, self.settings.smtp_port) as smtp:
                self._login_and_send(smtp, msg)
        else:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as smtp:
                if self.settings.smtp_use_tls:
                    smtp.starttls()
                self._login_and_send(smtp, msg)
        return True

    def send_test(self, dry_run: bool = False) -> bool:
        return self.send_report(
            "PC恐怖游戏日报 - SMTP 测试",
            "<p>SMTP 配置测试成功。</p>",
            Path("__missing__.md"),
            dry_run=dry_run,
        )

    def _login_and_send(self, smtp, msg: EmailMessage) -> None:
        if self.settings.smtp_user:
            smtp.login(self.settings.smtp_user, self.settings.smtp_password)
        smtp.send_message(msg)
