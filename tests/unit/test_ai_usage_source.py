"""Tests unitarios del protocolo UsageSource (fase 2 IA, conformidad estructural ISP)."""

import pytest

from doc_organize.ai import GitHubCopilotUsageClient, LiteLLMUsageClient, UsageSource
from doc_organize.core.models import GitHubCopilotUsageConfig, LiteLLMUsageConfig


def test_litellm_usage_client_satisfies_usage_source_protocol() -> None:
    client = LiteLLMUsageClient(LiteLLMUsageConfig(base_url="https://litellm.example.com", virtual_key="sk-test"))
    assert isinstance(client, UsageSource)


@pytest.mark.filterwarnings("ignore::DeprecationWarning")  # obsoleto desde 2.1.0
def test_github_copilot_usage_client_satisfies_usage_source_protocol() -> None:
    client = GitHubCopilotUsageClient(GitHubCopilotUsageConfig(username="octocat", personal_access_token="github_pat_test"))
    assert isinstance(client, UsageSource)
