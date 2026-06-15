from pathlib import Path

from horror_daily.config import Settings
from horror_daily.services.mailer import Mailer


def test_mailer_dry_run_does_not_send():
    settings = Settings(mail_from="a@example.com", mail_to="b@example.com", smtp_host="smtp.example.com")

    assert Mailer(settings).send_report("subject", "<p>ok</p>", Path("missing.md"), dry_run=True) is False
