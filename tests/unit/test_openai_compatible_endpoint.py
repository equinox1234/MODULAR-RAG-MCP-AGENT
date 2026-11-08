from types import SimpleNamespace

from src.libs.llm.openai_llm import OpenAILLM


def test_configured_compatible_endpoint_uses_bearer_without_azure_version():
    settings = SimpleNamespace(llm=SimpleNamespace(
        model="test-model", temperature=0, max_tokens=128, api_key="dummy",
        base_url="https://example.invalid/v1", azure_endpoint="https://azure.invalid",
        api_version="old-version"))
    provider = OpenAILLM(settings)
    assert provider.base_url == "https://example.invalid/v1"
    assert not provider._use_azure_auth
    assert provider.api_version is None


def test_explicit_endpoint_override_has_priority():
    settings = SimpleNamespace(llm=SimpleNamespace(
        model="test-model", temperature=0, max_tokens=128, api_key="dummy",
        base_url="https://configured.invalid/v1"))
    assert OpenAILLM(settings, base_url="https://override.invalid/v1").base_url == "https://override.invalid/v1"
