import pytest

from app import config
from app.azure_reasoner import AzureOpenAIReasoner
from app.config import Settings
from app.errors import ConfigurationError
from app.reasoner import RuleBasedReasoner, create_reasoner


def test_baseline_default_ignores_azure_configuration(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "broken")
    assert isinstance(create_reasoner(), RuleBasedReasoner)


def test_missing_azure_settings_and_unknown_provider(monkeypatch):
    monkeypatch.setenv("REASONER_PROVIDER", "azure_openai")
    with pytest.raises(ConfigurationError):
        create_reasoner()
    monkeypatch.setenv("REASONER_PROVIDER", "typo")
    with pytest.raises(ConfigurationError):
        create_reasoner()


def test_dotenv_preserves_environment(monkeypatch):
    (config.ROOT / ".env").write_text(
        "REASONER_PROVIDER=azure_openai\nAZURE_OPENAI_DEPLOYMENT=file-deployment\n"
        "AZURE_OPENAI_API_KEY=file-key\nAZURE_OPENAI_BASE_URL=https://example.openai.azure.com/openai/v1/\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "environment-deployment")
    settings = Settings.from_env()
    assert settings.provider == "azure_openai"
    assert settings.deployment == "environment-deployment"
    assert settings.api_key == "file-key"
    assert "file-key" not in repr(settings)
    assert settings.timeout_seconds == 30
    assert settings.max_output_tokens == 4096


@pytest.mark.parametrize("variable,value", [
    ("AZURE_OPENAI_BASE_URL", "http://example/openai/v1/"),
    ("AZURE_OPENAI_BASE_URL", "https://example/api/projects/project"),
    ("AZURE_OPENAI_BASE_URL", "https://user:secret@example/openai/v1/"),
    ("AZURE_OPENAI_TIMEOUT_SECONDS", "nan"),
    ("AZURE_OPENAI_TIMEOUT_SECONDS", "0"),
    ("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "-1"),
    ("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "broken"),
])
def test_invalid_settings(monkeypatch, variable, value):
    for key, setting in {
        "REASONER_PROVIDER": "azure_openai", "AZURE_OPENAI_API_KEY": "key",
        "AZURE_OPENAI_BASE_URL": "https://example.openai.azure.com/openai/v1/",
        "AZURE_OPENAI_DEPLOYMENT": "deployment", variable: value,
    }.items():
        monkeypatch.setenv(key, setting)
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_sdk_configuration_has_no_retries(monkeypatch):
    captured = {}

    def client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("app.azure_reasoner.OpenAI", client)
    AzureOpenAIReasoner(Settings(
        provider="azure_openai", base_url="https://example.openai.azure.com/openai/v1",
        api_key="key", deployment="model", timeout_seconds=12, max_output_tokens=200,
    ))
    assert captured["timeout"] == 12
    assert captured["max_retries"] == 0
    assert captured["base_url"].endswith("/openai/v1/")
