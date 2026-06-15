import httpx

from horror_daily.services.http import build_timeout, describe_http_error


def test_build_timeout_uses_split_values():
    timeout = build_timeout(
        {
            "runtime": {
                "request_timeout_seconds": 20,
                "connect_timeout_seconds": 12,
                "read_timeout_seconds": 25,
            }
        }
    )

    assert timeout.connect == 12
    assert timeout.read == 25


def test_describe_connect_timeout():
    message = describe_http_error(httpx.ConnectTimeout("slow TLS"))

    assert "connect timeout" in message
