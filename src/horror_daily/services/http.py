from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


DEFAULT_USER_AGENT = "horror-daily/0.1 (+PC horror game daily report)"


@dataclass(slots=True)
class NetworkDiagnostic:
    name: str
    url: str
    ok: bool
    elapsed_seconds: float
    status_code: int | None = None
    bytes_read: int = 0
    error: str = ""


def build_timeout(config: dict) -> httpx.Timeout:
    runtime = config.get("runtime", {})
    legacy = float(runtime.get("request_timeout_seconds", 20))
    return httpx.Timeout(
        connect=float(runtime.get("connect_timeout_seconds", max(legacy, 10))),
        read=float(runtime.get("read_timeout_seconds", max(legacy, 20))),
        write=float(runtime.get("write_timeout_seconds", 10)),
        pool=float(runtime.get("pool_timeout_seconds", 10)),
    )


def build_limits(config: dict) -> httpx.Limits:
    runtime = config.get("runtime", {})
    return httpx.Limits(
        max_connections=int(runtime.get("max_connections", 8)),
        max_keepalive_connections=int(runtime.get("max_keepalive_connections", 4)),
        keepalive_expiry=float(runtime.get("keepalive_expiry_seconds", 60)),
    )


def build_headers(config: dict) -> dict[str, str]:
    runtime = config.get("runtime", {})
    return {"User-Agent": runtime.get("user_agent", DEFAULT_USER_AGENT)}


def build_client(config: dict) -> httpx.Client:
    return httpx.Client(
        timeout=build_timeout(config),
        limits=build_limits(config),
        headers=build_headers(config),
        follow_redirects=True,
        http2=False,
    )


def describe_http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return f"connect timeout/TLS handshake slow: {exc}"
    if isinstance(exc, httpx.ReadTimeout):
        return f"read timeout after connection: {exc}"
    if isinstance(exc, httpx.PoolTimeout):
        return f"connection pool timeout: {exc}"
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        return f"HTTP {response.status_code} from {response.url}"
    if isinstance(exc, httpx.RequestError):
        return f"request error: {exc}"
    return str(exc)


def diagnose_url(client: httpx.Client, name: str, url: str) -> NetworkDiagnostic:
    started = time.perf_counter()
    try:
        response = client.get(url)
        response.raise_for_status()
        return NetworkDiagnostic(
            name=name,
            url=url,
            ok=True,
            elapsed_seconds=round(time.perf_counter() - started, 2),
            status_code=response.status_code,
            bytes_read=len(response.content),
        )
    except Exception as exc:
        return NetworkDiagnostic(
            name=name,
            url=url,
            ok=False,
            elapsed_seconds=round(time.perf_counter() - started, 2),
            error=describe_http_error(exc),
        )
