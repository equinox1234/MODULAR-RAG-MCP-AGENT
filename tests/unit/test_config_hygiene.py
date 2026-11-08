"""Configuration hygiene: env-var secrets, metric/provider validation, no leaks."""


import pytest

from src.core.settings import (
    REPO_ROOT,
    SettingsError,
    expand_env_vars,
    load_settings,
    validate_settings,
)


def _minimal_config(**overrides):
    """A complete settings mapping that passes validation."""
    config = {
        "llm": {
            "provider": "openai",
            "model": "gpt-test",
            "temperature": 0.0,
            "max_tokens": 128,
            "api_key": "${TEST_API_KEY}",
        },
        "embedding": {"provider": "openai", "model": "emb", "dimensions": 8},
        "vector_store": {
            "provider": "chroma",
            "persist_directory": "./data/db/chroma",
            "collection_name": "test",
        },
        "retrieval": {
            "dense_top_k": 5,
            "sparse_top_k": 5,
            "fusion_top_k": 3,
            "rrf_k": 60,
        },
        "rerank": {"enabled": False, "provider": "none", "model": "m", "top_k": 3},
        "evaluation": {"enabled": False, "provider": "custom", "metrics": ["hit_rate"]},
        "observability": {
            "log_level": "INFO",
            "trace_enabled": False,
            "trace_file": "./logs/traces.jsonl",
            "structured_logging": True,
        },
    }
    config.update(overrides)
    return config


# ============================================================================
# ${VAR} expansion
# ============================================================================

def test_env_reference_is_expanded(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret-from-env")
    expanded = expand_env_vars({"llm": {"api_key": "${TEST_API_KEY}"}})
    assert expanded["llm"]["api_key"] == "secret-from-env"


def test_env_fallback_is_used_when_unset(monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    expanded = expand_env_vars({"x": "${MISSING_KEY:-fallback}"})
    assert expanded["x"] == "fallback"


def test_unset_variable_becomes_empty_and_warns(monkeypatch, caplog):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with caplog.at_level("WARNING"):
        expanded = expand_env_vars({"x": "${MISSING_KEY}"})
    assert expanded["x"] == ""
    assert "MISSING_KEY" in caplog.text


def test_expansion_is_recursive(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "k")
    expanded = expand_env_vars({"a": ["${TEST_API_KEY}"], "b": {"c": "x-${TEST_API_KEY}"}})
    assert expanded == {"a": ["k"], "b": {"c": "x-k"}}


def test_load_settings_reads_env_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "from-env")
    config_file = tmp_path / "settings.yaml"
    import yaml

    config_file.write_text(yaml.safe_dump(_minimal_config()), encoding="utf-8")

    settings = load_settings(config_file)

    assert settings.llm.api_key == "from-env"


# ============================================================================
# Metrics must match the configured evaluator
# ============================================================================

def test_enabled_custom_evaluator_rejects_ragas_metric(tmp_path):
    import yaml

    config = _minimal_config(
        evaluation={
            "enabled": True,
            "provider": "custom",
            "metrics": ["hit_rate", "faithfulness"],
        }
    )
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(SettingsError) as excinfo:
        load_settings(config_file)
    assert "faithfulness" in str(excinfo.value)
    assert "custom" in str(excinfo.value)


def test_enabled_ragas_evaluator_accepts_faithfulness(tmp_path):
    import yaml

    config = _minimal_config(
        evaluation={
            "enabled": True,
            "provider": "ragas",
            "metrics": ["faithfulness", "answer_relevancy"],
        }
    )
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert load_settings(config_file).evaluation.provider == "ragas"


def test_disabled_evaluation_does_not_block_loading():
    from src.core.settings import Settings

    config = _minimal_config(
        evaluation={
            "enabled": False,
            "provider": "custom",
            "metrics": ["faithfulness"],
        }
    )
    validate_settings(Settings.from_dict(config))  # must not raise


# ============================================================================
# No credentials in tracked config files
# ============================================================================

def test_config_files_contain_no_literal_api_keys():
    """A real key pasted back into config/ must fail this test, not a commit."""
    suspicious = []
    for config_file in sorted((REPO_ROOT / "config").glob("*.yaml")):
        text = config_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("api_key"):
                continue
            value = stripped.split(":", 1)[-1].strip().strip("\"'")
            if not value:
                continue
            if value.startswith("${") or value.startswith("<"):
                continue  # env reference or placeholder
            if value.lower().startswith(("your", "sk-xxx", "none")):
                continue
            suspicious.append(f"{config_file.name}: {stripped}")
    assert not suspicious, (
        "Literal credentials found in config files; use ${ENV_VAR} instead:\n"
        + "\n".join(suspicious)
    )
