"""Tests unitarios de GitHubCopilotUsageClient (fase 2 IA, monitorización de uso/coste)."""

import httpx
import pytest

from doc_organize.ai import GitHubCopilotUsageClient, github_copilot_usage_config_from_env
from doc_organize.core.exceptions import UsageSourceAuthError, UsageSourceError
from doc_organize.core.models import GitHubCopilotUsageConfig, UsageSourceName

_CONFIG = GitHubCopilotUsageConfig(username="octocat", personal_access_token="github_pat_test")


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_get_usage_normalizes_usage_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/users/octocat/settings/billing/premium_request/usage"
        assert request.url.params["year"] == "2026"
        assert request.url.params["month"] == "9"
        assert request.headers["authorization"] == "Bearer github_pat_test"
        assert request.headers["accept"] == "application/vnd.github+json"
        return httpx.Response(
            200,
            json={
                "usageItems": [
                    {
                        "date": "2026-09-01",
                        "product": "copilot",
                        "sku": "premium_request",
                        "quantity": 42,
                        "unitType": "premium_requests",
                        "netAmount": 0.0,
                    }
                ]
            },
        )

    async with GitHubCopilotUsageClient(_CONFIG, transport=_transport(handler)) as client:
        snapshot = await client.get_usage(year=2026, month=9)

    assert snapshot.source == UsageSourceName.GITHUB_COPILOT
    assert snapshot.period_start == "2026-09-01"
    assert snapshot.period_end == "2026-09-30"
    assert len(snapshot.items) == 1
    assert snapshot.items[0].quantity == 42
    assert snapshot.items[0].unit_type == "premium_requests"


@pytest.mark.asyncio
async def test_get_usage_defaults_year_to_current_year_when_omitted() -> None:
    from datetime import date

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["year"] == str(date.today().year)
        assert "month" not in request.url.params
        return httpx.Response(200, json={"usageItems": []})

    async with GitHubCopilotUsageClient(_CONFIG, transport=_transport(handler)) as client:
        snapshot = await client.get_usage()

    assert snapshot.items == []


@pytest.mark.asyncio
async def test_get_usage_raises_auth_error_on_403() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"})

    async with GitHubCopilotUsageClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(UsageSourceAuthError):
            await client.get_usage()


@pytest.mark.asyncio
async def test_get_usage_raises_usage_source_error_on_other_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "internal"})

    async with GitHubCopilotUsageClient(_CONFIG, transport=_transport(handler)) as client:
        with pytest.raises(UsageSourceError):
            await client.get_usage()


def test_github_copilot_usage_config_from_env_requires_both_vars(monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_GITHUB_USERNAME", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_GITHUB_PAT", raising=False)
    with pytest.raises(ValueError):
        github_copilot_usage_config_from_env()


def test_github_copilot_usage_config_from_env_reads_both_vars(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_GITHUB_USERNAME", "octocat")
    monkeypatch.setenv("DOC_ORGANIZE_GITHUB_PAT", "github_pat_from_env")

    config = github_copilot_usage_config_from_env()

    assert config.username == "octocat"
    assert config.personal_access_token == "github_pat_from_env"
