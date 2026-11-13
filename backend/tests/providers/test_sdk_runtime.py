"""Concurrency and proxy contracts for process-global provider SDKs."""

import asyncio
import threading
from contextlib import contextmanager

import pytest

import app.providers.sdk_runtime as runtime
from app.providers.errors import ProviderBusy


def test_nonblocking_runtime_returns_busy_without_entering_nested_call() -> None:
    started = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with runtime.provider_runtime("akshare", None, wait=True):
            started.set()
            release.wait(timeout=2)

    worker = threading.Thread(target=hold_lock)
    worker.start()
    assert started.wait(timeout=1)
    with pytest.raises(ProviderBusy) as captured:
        with runtime.provider_runtime("akshare", None, wait=False):
            raise AssertionError("busy runtime must not enter the SDK")

    release.set()
    worker.join(timeout=1)
    assert captured.value.detail == "Data source is currently in use, retry later"


def test_reentrant_runtime_allows_the_same_worker_to_continue() -> None:
    entered = False

    with runtime.provider_runtime("akshare", None, wait=True):
        with runtime.provider_runtime("akshare", None, wait=False):
            entered = True

    assert entered is True


def test_waiting_runtime_queues_until_the_current_sdk_call_exits() -> None:
    attempting = threading.Event()
    entered_second = threading.Event()
    finished = threading.Event()

    with runtime.provider_runtime("akshare", None, wait=True):
        def second_call() -> None:
            attempting.set()
            with runtime.provider_runtime("akshare", None, wait=True):
                entered_second.set()
            finished.set()

        worker = threading.Thread(target=second_call)
        worker.start()
        assert attempting.wait(timeout=1)
        assert not entered_second.wait(timeout=0.05)

    worker.join(timeout=1)
    assert finished.is_set()


@pytest.mark.anyio
async def test_cooperative_timeout_does_not_release_the_sdk_lock_early() -> None:
    started = threading.Event()
    release = threading.Event()
    exited = threading.Event()

    def long_sdk_call() -> None:
        with runtime.provider_runtime("yfinance", None, wait=True):
            started.set()
            release.wait(timeout=2)
            exited.set()

    worker = asyncio.create_task(asyncio.to_thread(long_sdk_call))
    await asyncio.to_thread(started.wait)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(worker, timeout=0.01)

    with pytest.raises(ProviderBusy):
        with runtime.provider_runtime("yfinance", None, wait=False):
            pass

    release.set()
    await asyncio.to_thread(exited.wait)
    with runtime.provider_runtime("yfinance", None, wait=False):
        pass


def test_akshare_proxy_context_covers_the_complete_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []

    @contextmanager
    def fake_proxy_context(proxies: object):
        events.append(("enter", proxies))
        yield
        events.append(("exit", proxies))

    monkeypatch.setattr(runtime.ak, "ProxyContext", fake_proxy_context)
    proxy_url = "socks5h://127.0.0.1:1080"

    with runtime.provider_runtime("akshare", proxy_url, wait=True):
        events.append(("sdk-call", None))

    assert events == [
        ("enter", {"http": proxy_url, "https": proxy_url}),
        ("sdk-call", None),
        ("exit", {"http": proxy_url, "https": proxy_url}),
    ]


def test_akshare_direct_mode_explicitly_disables_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []

    @contextmanager
    def fake_proxy_context(proxies: object):
        observed.append(proxies)
        yield

    monkeypatch.setattr(runtime.ak, "ProxyContext", fake_proxy_context)

    with runtime.provider_runtime("akshare", None, wait=True):
        pass

    assert observed == [{"http": None, "https": None}]


def test_yahoo_proxy_is_set_inside_its_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured: list[object] = []
    monkeypatch.setattr(
        runtime.yf, "set_config", lambda *, proxy: configured.append(proxy)
    )
    proxy_url = "http://127.0.0.1:8080"

    with runtime.provider_runtime("yfinance", proxy_url, wait=True):
        configured.append("sdk-call")
    with runtime.provider_runtime("yfinance", None, wait=True):
        pass

    assert configured == [proxy_url, "sdk-call", None]


def test_different_sdk_families_do_not_block_each_other() -> None:
    with runtime.provider_runtime("akshare", None, wait=True):
        with runtime.provider_runtime("yfinance", None, wait=False):
            pass


def test_baostock_runtime_rejects_proxy_configuration() -> None:
    with pytest.raises(ValueError, match="BaoStock"):
        with runtime.provider_runtime("baostock", "http://127.0.0.1:8080", wait=True):
            pass


def test_native_ccxt_runtime_does_not_use_a_global_sdk_lock() -> None:
    entered = False

    with runtime.provider_runtime(
        "binance", "socks5h://127.0.0.1:1080", wait=False
    ):
        entered = True

    assert entered is True


def test_unknown_runtime_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="provider"):
        with runtime.provider_runtime("unknown", None, wait=True):
            pass
