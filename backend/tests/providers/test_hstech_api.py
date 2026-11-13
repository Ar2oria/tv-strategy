"""Paginated iTiger HSTECH constituent API tests with a dummy token."""

from unittest.mock import Mock

import httpx
import pytest
import respx

import app.providers.hstech_api as api
import app.providers.hstech_api as universe_adapter
from app.domain.dto import UniverseSnapshot
from app.providers.errors import ProviderConfigurationError, ProviderDataInvalid

API_URL = "https://hq.skytigris.cn/hkstock/market/index/package_HSTECH"
TOKEN = "dummy-test-token"


def payload(
    rows: list[list[object]],
    *,
    page: int,
    total_count: int = 30,
    total_page: int = 2,
) -> dict[str, object]:
    return {
        "delay": 0,
        "ret": 0,
        "serverTime": 1794464084681,
        "topics": [
            {
                "headers": ["名称代码", "最新价格", "涨跌幅"],
                "data": rows,
                "totalPage": total_page,
                "name": "恒生科技指数",
                "id": "package_HSTECH",
                "page": page,
                "totalCount": total_count,
            }
        ],
    }


def rows(start: int, stop: int) -> list[list[object]]:
    return [[f"{index:05d}", f"Stock {index}", 10.0, 0.0] for index in range(start, stop)]


def test_downloads_all_pages_and_preserves_canonical_hk_symbols() -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(API_URL).mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=payload(
                    rows(1, 21) if request.url.params["page"] == "0" else rows(21, 31),
                    page=int(request.url.params["page"]),
                ),
            )
        )

        snapshot = api.fetch_hstech_api_snapshot(
            proxy_url=None,
            request_timeout_seconds=5,
            bearer_token=TOKEN,
            now_ms=lambda: 1794463635084,
        )

    assert [call.request.url.params["page"] for call in route.calls] == ["0", "1"]
    assert route.calls[0].request.headers["authorization"] == f"Bearer {TOKEN}"
    assert route.calls[0].request.url.params["size"] == "20"
    assert snapshot.universe_code == "hstech"
    assert snapshot.source == "itiger"
    assert snapshot.effective_date is None
    assert len(snapshot.members) == 30
    assert snapshot.members[0].symbol == "0001.HK"
    assert snapshot.members[-1].symbol == "0030.HK"
    assert all(member.market == "hk_stock" for member in snapshot.members)
    assert all(member.exchange == "HKEX" for member in snapshot.members)
    assert all(member.instrument_type == "stock" for member in snapshot.members)
    assert snapshot.related_instruments[0].symbol == "HSTECH.HK"


def test_fetches_every_declared_page_even_when_count_already_matches() -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(API_URL).mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=payload(
                    rows(1, 21)
                    if request.url.params["page"] == "0"
                    else rows(21, 31)
                    if request.url.params["page"] == "1"
                    else [],
                    page=int(request.url.params["page"]),
                    total_page=3,
                ),
            )
        )

        snapshot = api.fetch_hstech_api_snapshot(
            proxy_url=None,
            request_timeout_seconds=5,
            bearer_token=TOKEN,
        )

    assert [call.request.url.params["page"] for call in route.calls] == ["0", "1", "2"]
    assert len(snapshot.members) == 30


def test_total_page_changes_between_responses_are_rejected() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(API_URL).mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=payload(
                    rows(1, 21)
                    if request.url.params["page"] == "0"
                    else rows(21, 31),
                    page=int(request.url.params["page"]),
                    total_page=2 if request.url.params["page"] == "0" else 100,
                ),
            )
        )

        with pytest.raises(ProviderDataInvalid, match="totalPage"):
            api.fetch_hstech_api_snapshot(
                proxy_url=None,
                request_timeout_seconds=5,
                bearer_token=TOKEN,
            )


def test_non_ascii_constituent_codes_are_rejected() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(API_URL).respond(
            json=payload([["００７００", "腾讯控股", 404.8, -0.01]], page=0, total_count=1)
        )

        with pytest.raises(ProviderDataInvalid, match="code"):
            api.fetch_hstech_api_snapshot(
                proxy_url=None,
                request_timeout_seconds=5,
                bearer_token=TOKEN,
            )


def test_canonical_four_digit_code_matches_existing_hk_catalog() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(API_URL).respond(
            json=payload([["00700", "腾讯控股", 404.8, -0.01]], page=0, total_count=1, total_page=1)
        )

        snapshot = api.fetch_hstech_api_snapshot(
            proxy_url=None,
            request_timeout_seconds=5,
            bearer_token=TOKEN,
        )

    assert snapshot.members[0].symbol == "0700.HK"
    assert snapshot.members[0].provider_symbol == "0700.HK"
    assert snapshot.members[0].name == "腾讯控股"


@pytest.mark.parametrize(
    "payload_override",
    [
        {"ret": 500},
        {"topics": []},
        {"topics": [{"data": [], "page": 0, "totalCount": 1, "totalPage": 1}]},
    ],
    ids=["bad-ret", "missing-topics", "count-mismatch"],
)
def test_invalid_api_schema_fails_without_returning_partial_members(
    payload_override: dict[str, object],
) -> None:
    response = payload(rows(1, 2), page=0, total_count=1)
    response.update(payload_override)

    with respx.mock(assert_all_called=True) as mock:
        mock.get(API_URL).respond(json=response)
        with pytest.raises(ProviderDataInvalid):
            api.fetch_hstech_api_snapshot(
                proxy_url=None,
                request_timeout_seconds=5,
                bearer_token=TOKEN,
            )


def test_duplicate_constituents_across_pages_are_rejected() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(API_URL).mock(
            side_effect=lambda request: httpx.Response(
                200,
                json=payload(
                    [["00700", "腾讯控股", 404.8, -0.01]
                    if request.url.params["page"] == "0"
                    else ["00700", "腾讯控股-duplicate", 400.0, -0.02]],
                    page=int(request.url.params["page"]),
                    total_count=2,
                ),
            )
        )

        with pytest.raises(ProviderDataInvalid, match="Duplicate"):
            api.fetch_hstech_api_snapshot(
                proxy_url=None,
                request_timeout_seconds=5,
                bearer_token=TOKEN,
            )


def test_itiger_provider_uses_api_with_configured_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = UniverseSnapshot(
        universe_code="hstech",
        source="itiger",
        effective_date=None,
        members=(),
    )
    call = Mock(return_value=expected)
    monkeypatch.setattr(universe_adapter, "fetch_hstech_api_snapshot", call)
    proxy_url = "socks5h://127.0.0.1:1080"
    provider = universe_adapter.ItigerUniverseProvider(
        request_timeout_seconds=7.5,
        proxy_url=proxy_url,
        bearer_token=TOKEN,
    )

    assert provider.fetch_universe("hstech") is expected
    call.assert_called_once_with(
        proxy_url=proxy_url,
        request_timeout_seconds=7.5,
        bearer_token=TOKEN,
    )


def test_blank_token_is_rejected_before_any_http_request() -> None:
    with respx.mock(assert_all_called=False):
        with pytest.raises(ProviderConfigurationError):
            api.fetch_hstech_api_snapshot(
                proxy_url=None,
                request_timeout_seconds=5,
                bearer_token="   ",
            )
