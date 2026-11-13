"""Serialize process-global SDK proxy state with optional busy detection."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import akshare as ak
import yfinance as yf

from app.providers.errors import ProviderBusy

class OccupancyLock:
    """An RLock with a separately protected occupancy count."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._active = 0

    def acquire(self, blocking: bool = True) -> bool:
        acquired = self._lock.acquire(blocking=blocking)
        if acquired:
            with self._state_lock:
                self._active += 1
        return acquired

    def release(self) -> None:
        with self._state_lock:
            self._active -= 1
        self._lock.release()

    def busy(self) -> bool:
        with self._state_lock:
            return self._active > 0


_LOCKS = {
    "akshare": OccupancyLock(),
    "yfinance": OccupancyLock(),
    "baostock": OccupancyLock(),
}


def provider_busy(provider_name: str) -> bool:
    """Report occupancy without acquiring or releasing across event-loop threads."""
    if provider_name in {"binance", "okx"}:
        return False
    if provider_name not in _LOCKS:
        raise ValueError(f"Unknown SDK provider: {provider_name}")
    return _LOCKS[provider_name].busy()


@contextmanager
def provider_runtime(
    provider_name: str,
    proxy_url: str | None,
    *,
    wait: bool,
) -> Iterator[None]:
    """Own one SDK's complete proxy configuration and call boundary."""
    if provider_name in {"binance", "okx"}:
        yield
        return
    if provider_name not in _LOCKS:
        raise ValueError(f"Unknown SDK provider: {provider_name}")
    if provider_name == "baostock" and proxy_url is not None:
        raise ValueError("BaoStock does not support proxy configuration")
    lock = _LOCKS[provider_name]
    acquired = lock.acquire(blocking=wait)
    if not acquired:
        raise ProviderBusy()
    try:
        if provider_name == "akshare":
            proxies = {"http": proxy_url, "https": proxy_url}
            with ak.ProxyContext(proxies):
                yield
        elif provider_name == "yfinance":
            yf.set_config(proxy=proxy_url)
            yield
        else:
            yield
    finally:
        lock.release()
