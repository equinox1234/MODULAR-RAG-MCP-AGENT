"""Configuration loading and validation for the Modular RAG MCP Server."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repo root & path resolution
# ---------------------------------------------------------------------------
# Anchored to this file's location: <repo>/src/core/settings.py → parents[2]
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------
# Config values may reference environment variables as ``${NAME}`` or
# ``${NAME:-fallback}``.  Secrets therefore never need to live in a tracked
# YAML file: put them in ``.env`` (gitignored) or in the process environment.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_DOTENV_LOADED = False

# Default absolute path to settings.yaml
DEFAULT_SETTINGS_PATH: Path = REPO_ROOT / "config" / "settings.yaml"


def resolve_path(relative: Union[str, Path]) -> Path:
    """Resolve a repo-relative path to an absolute path.

    If *relative* is already absolute it is returned as-is.  Otherwise
    it is resolved against :data:`REPO_ROOT`.

    >>> resolve_path("config/settings.yaml")  # doctest: +SKIP
    PosixPath('/home/user/Modular-RAG-MCP-Server/config/settings.yaml')
    """
    p = Path(relative)
    if p.is_absolute():
        return p
    return (REPO_ROOT / p).resolve()


class SettingsError(ValueError):
    """Raised when settings validation fails."""


def load_dotenv(path: Union[str, Path] | None = None) -> None:
    """Load ``KEY=VALUE`` pairs from a ``.env`` file into ``os.environ``.

    Existing environment variables always win, so a shell export overrides the
    file.  Missing files are ignored.  This keeps secrets out of tracked YAML
    without adding a dependency on ``python-dotenv``.
    """
    global _DOTENV_LOADED
    dotenv_path = Path(path) if path is not None else REPO_ROOT / ".env"
    if not dotenv_path.is_file():
        return
    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            if not key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except OSError as exc:  # unreadable .env must not break configuration
        logger.warning("Could not read %s: %s", dotenv_path, exc)
    _DOTENV_LOADED = True


def _expand_env(value: Any, missing: set[str]) -> Any:
    """Recursively substitute ``${VAR}`` references in loaded settings."""
    if isinstance(value, dict):
        return {key: _expand_env(item, missing) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item, missing) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name, fallback = match.group(1), match.group(2)
        if name in os.environ:
            return os.environ[name]
        if fallback is not None:
            return fallback
        missing.add(name)
        return ""

    return _ENV_REF.sub(replace, value)


def expand_env_vars(data: Any) -> Any:
    """Expand ``${VAR}`` / ``${VAR:-default}`` in a parsed settings mapping.

    Unset variables without a fallback become empty strings and are reported
    through a warning, so a missing credential surfaces as a clear auth error
    instead of a literal ``${...}`` being sent to a provider.
    """
    if not _DOTENV_LOADED:
        load_dotenv()
    missing: set[str] = set()
    expanded = _expand_env(data, missing)
    if missing:
        logger.warning(
            "Settings reference unset environment variables (left empty): %s. "
            "Define them in .env or the process environment.",
            ", ".join(sorted(missing)),
        )
    return expanded


def _require_mapping(data: Dict[str, Any], key: str, path: str) -> Dict[str, Any]:
    value = data.get(key)
    if value is None:
        raise SettingsError(f"Missing required field: {path}.{key}")
    if not isinstance(value, dict):
        raise SettingsError(f"Expected mapping for field: {path}.{key}")
    return value


def _require_value(data: Dict[str, Any], key: str, path: str) -> Any:
    if key not in data or data.get(key) is None:
        raise SettingsError(f"Missing required field: {path}.{key}")
    return data[key]


def _require_str(data: Dict[str, Any], key: str, path: str) -> str:
    value = _require_value(data, key, path)
    if not isinstance(value, str) or not value.strip():
        raise SettingsError(f"Expected non-empty string for field: {path}.{key}")
    return value


def _require_int(data: Dict[str, Any], key: str, path: str) -> int:
    value = _require_value(data, key, path)
    if not isinstance(value, int):
        raise SettingsError(f"Expected integer for field: {path}.{key}")
    return value


def _require_number(data: Dict[str, Any], key: str, path: str) -> float:
    value = _require_value(data, key, path)
    if not isinstance(value, (int, float)):
        raise SettingsError(f"Expected number for field: {path}.{key}")
    return float(value)


def _require_bool(data: Dict[str, Any], key: str, path: str) -> bool:
    value = _require_value(data, key, path)
    if not isinstance(value, bool):
        raise SettingsError(f"Expected boolean for field: {path}.{key}")
    return value


def _require_list(data: Dict[str, Any], key: str, path: str) -> List[Any]:
    value = _require_value(data, key, path)
    if not isinstance(value, list):
        raise SettingsError(f"Expected list for field: {path}.{key}")
    return value


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    temperature: float
    max_tokens: int
    # Azure/OpenAI-specific optional fields
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    azure_endpoint: Optional[str] = None
    deployment_name: Optional[str] = None
    # Ollama-specific optional fields
    base_url: Optional[str] = None


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    model: str
    dimensions: int
    # Azure-specific optional fields
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    azure_endpoint: Optional[str] = None
    deployment_name: Optional[str] = None
    # Ollama-specific optional fields
    base_url: Optional[str] = None


@dataclass(frozen=True)
class VectorStoreSettings:
    provider: str
    persist_directory: str
    collection_name: str


@dataclass(frozen=True)
class RetrievalSettings:
    dense_top_k: int
    sparse_top_k: int
    fusion_top_k: int
    rrf_k: int


@dataclass(frozen=True)
class RerankSettings:
    enabled: bool
    provider: str
    model: str
    top_k: int


@dataclass(frozen=True)
class EvaluationSettings:
    enabled: bool
    provider: str
    metrics: List[str]


@dataclass(frozen=True)
class ObservabilitySettings:
    log_level: str
    trace_enabled: bool
    trace_file: str
    structured_logging: bool


@dataclass(frozen=True)
class VisionLLMSettings:
    enabled: bool
    provider: str
    model: str
    max_image_size: int
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    azure_endpoint: Optional[str] = None
    deployment_name: Optional[str] = None
    base_url: Optional[str] = None


@dataclass(frozen=True)
class IngestionSettings:
    chunk_size: int
    chunk_overlap: int
    splitter: str
    batch_size: int
    chunk_refiner: Optional[Dict[str, Any]] = None  # 动态配置
    metadata_enricher: Optional[Dict[str, Any]] = None  # 动态配置


@dataclass(frozen=True)
class ModbusSettings:
    """Optional Modbus domain retrieval configuration.

    ``retrieval_mode`` selects the backend used by :class:`ModbusKnowledge`:

    - ``hybrid`` : framework ``HybridSearch`` (dense + BM25 + RRF), which
      requires the dense index built by ``scripts.build_modbus_dense_index``
      and an embedding API call per query (shipped default);
    - ``bm25``   : offline keyword retrieval, no model or network calls.

    When the ``modbus`` section is absent the service falls back to ``bm25``
    so an old config file keeps working without network access.
    """

    retrieval_mode: str = "bm25"
    dense_top_k: int = 20
    sparse_top_k: int = 20
    fusion_top_k: int = 20
    # RRF weight for the BM25 (sparse) list relative to dense (1.0 = equal).
    # Protocol text is terminology-heavy, so sparse generally deserves a bit
    # more weight than a generic corpus would.
    hybrid_sparse_weight: float = 1.0
    # Optional second-stage rerank of the fused candidates. Off by default:
    # the LLM reranker costs one model call and several seconds per query.
    rerank_enabled: bool = False
    rerank_provider: str = "llm"  # llm | cross_encoder (needs torch + local model)
    rerank_candidates: int = 8
    rerank_text_chars: int = 500
    # Concise prompt: no per-passage reasoning, so one rerank call stays cheap.
    rerank_prompt: str = "config/prompts/modbus_rerank.txt"


@dataclass(frozen=True)
class Settings:
    llm: LLMSettings
    embedding: EmbeddingSettings
    vector_store: VectorStoreSettings
    retrieval: RetrievalSettings
    rerank: RerankSettings
    evaluation: EvaluationSettings
    observability: ObservabilitySettings
    ingestion: Optional[IngestionSettings] = None
    vision_llm: Optional[VisionLLMSettings] = None
    modbus: Optional[ModbusSettings] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        if not isinstance(data, dict):
            raise SettingsError("Settings root must be a mapping")

        llm = _require_mapping(data, "llm", "settings")
        embedding = _require_mapping(data, "embedding", "settings")
        vector_store = _require_mapping(data, "vector_store", "settings")
        retrieval = _require_mapping(data, "retrieval", "settings")
        rerank = _require_mapping(data, "rerank", "settings")
        evaluation = _require_mapping(data, "evaluation", "settings")
        observability = _require_mapping(data, "observability", "settings")

        ingestion_settings = None
        if "ingestion" in data:
            ingestion = _require_mapping(data, "ingestion", "settings")
            ingestion_settings = IngestionSettings(
                chunk_size=_require_int(ingestion, "chunk_size", "ingestion"),
                chunk_overlap=_require_int(ingestion, "chunk_overlap", "ingestion"),
                splitter=_require_str(ingestion, "splitter", "ingestion"),
                batch_size=_require_int(ingestion, "batch_size", "ingestion"),
                chunk_refiner=ingestion.get("chunk_refiner"),  # 可选配置
                metadata_enricher=ingestion.get("metadata_enricher"),  # 可选配置
            )

        vision_llm_settings = None
        if "vision_llm" in data:
            vision_llm = _require_mapping(data, "vision_llm", "settings")
            vision_llm_settings = VisionLLMSettings(
                enabled=_require_bool(vision_llm, "enabled", "vision_llm"),
                provider=_require_str(vision_llm, "provider", "vision_llm"),
                model=_require_str(vision_llm, "model", "vision_llm"),
                max_image_size=_require_int(vision_llm, "max_image_size", "vision_llm"),
                api_key=vision_llm.get("api_key"),
                api_version=vision_llm.get("api_version"),
                azure_endpoint=vision_llm.get("azure_endpoint"),
                deployment_name=vision_llm.get("deployment_name"),
                base_url=vision_llm.get("base_url"),
            )

        modbus_settings = None
        if "modbus" in data:
            modbus = _require_mapping(data, "modbus", "settings")
            modbus_settings = ModbusSettings(
                retrieval_mode=str(modbus.get("retrieval_mode", "bm25")).strip().lower(),
                dense_top_k=int(modbus.get("dense_top_k", 20)),
                sparse_top_k=int(modbus.get("sparse_top_k", 20)),
                fusion_top_k=int(modbus.get("fusion_top_k", 20)),
                hybrid_sparse_weight=float(modbus.get("hybrid_sparse_weight", 1.0)),
                rerank_enabled=bool(modbus.get("rerank_enabled", False)),
                rerank_provider=str(modbus.get("rerank_provider", "llm")).strip().lower(),
                rerank_candidates=int(modbus.get("rerank_candidates", 8)),
                rerank_text_chars=int(modbus.get("rerank_text_chars", 500)),
                rerank_prompt=str(modbus.get("rerank_prompt", "config/prompts/modbus_rerank.txt")),
            )

        settings = cls(
            llm=LLMSettings(
                provider=_require_str(llm, "provider", "llm"),
                model=_require_str(llm, "model", "llm"),
                temperature=_require_number(llm, "temperature", "llm"),
                max_tokens=_require_int(llm, "max_tokens", "llm"),
                api_key=llm.get("api_key"),
                api_version=llm.get("api_version"),
                azure_endpoint=llm.get("azure_endpoint"),
                deployment_name=llm.get("deployment_name"),
                base_url=llm.get("base_url"),
            ),
            embedding=EmbeddingSettings(
                provider=_require_str(embedding, "provider", "embedding"),
                model=_require_str(embedding, "model", "embedding"),
                dimensions=_require_int(embedding, "dimensions", "embedding"),
                api_key=embedding.get("api_key"),
                api_version=embedding.get("api_version"),
                azure_endpoint=embedding.get("azure_endpoint"),
                deployment_name=embedding.get("deployment_name"),
                base_url=embedding.get("base_url"),
            ),
            vector_store=VectorStoreSettings(
                provider=_require_str(vector_store, "provider", "vector_store"),
                persist_directory=_require_str(vector_store, "persist_directory", "vector_store"),
                collection_name=_require_str(vector_store, "collection_name", "vector_store"),
            ),
            retrieval=RetrievalSettings(
                dense_top_k=_require_int(retrieval, "dense_top_k", "retrieval"),
                sparse_top_k=_require_int(retrieval, "sparse_top_k", "retrieval"),
                fusion_top_k=_require_int(retrieval, "fusion_top_k", "retrieval"),
                rrf_k=_require_int(retrieval, "rrf_k", "retrieval"),
            ),
            rerank=RerankSettings(
                enabled=_require_bool(rerank, "enabled", "rerank"),
                provider=_require_str(rerank, "provider", "rerank"),
                model=_require_str(rerank, "model", "rerank"),
                top_k=_require_int(rerank, "top_k", "rerank"),
            ),
            evaluation=EvaluationSettings(
                enabled=_require_bool(evaluation, "enabled", "evaluation"),
                provider=_require_str(evaluation, "provider", "evaluation"),
                metrics=[str(item) for item in _require_list(evaluation, "metrics", "evaluation")],
            ),
            observability=ObservabilitySettings(
                log_level=_require_str(observability, "log_level", "observability"),
                trace_enabled=_require_bool(observability, "trace_enabled", "observability"),
                trace_file=_require_str(observability, "trace_file", "observability"),
                structured_logging=_require_bool(observability, "structured_logging", "observability"),
            ),
            ingestion=ingestion_settings,
            vision_llm=vision_llm_settings,
            modbus=modbus_settings,
        )

        return settings


def validate_settings(settings: Settings) -> None:
    """Validate settings and raise SettingsError if invalid."""

    if not settings.llm.provider:
        raise SettingsError("Missing required field: llm.provider")
    if not settings.embedding.provider:
        raise SettingsError("Missing required field: embedding.provider")
    if not settings.vector_store.provider:
        raise SettingsError("Missing required field: vector_store.provider")
    if not settings.retrieval.rrf_k:
        raise SettingsError("Missing required field: retrieval.rrf_k")
    if not settings.rerank.provider:
        raise SettingsError("Missing required field: rerank.provider")
    if not settings.evaluation.provider:
        raise SettingsError("Missing required field: evaluation.provider")
    if not settings.observability.log_level:
        raise SettingsError("Missing required field: observability.log_level")

    _validate_evaluation_metrics(settings.evaluation)
    if settings.modbus is not None and settings.modbus.retrieval_mode not in {
        "bm25",
        "hybrid",
    }:
        raise SettingsError(
            f"modbus.retrieval_mode must be 'bm25' or 'hybrid', "
            f"got '{settings.modbus.retrieval_mode}'"
        )
    if (
        settings.modbus is not None
        and settings.modbus.rerank_enabled
        and settings.modbus.rerank_provider not in {"llm", "cross_encoder"}
    ):
        raise SettingsError(
            "modbus.rerank_provider must be 'llm' or 'cross_encoder', "
            f"got '{settings.modbus.rerank_provider}'"
        )


# Metrics each built-in evaluator can actually compute.  Kept here (not
# imported from the evaluator modules) so validating a config never pulls in
# ChromaDB, Ragas, or any other heavy dependency.
SUPPORTED_METRICS_BY_PROVIDER: Dict[str, frozenset[str]] = {
    "custom": frozenset({"hit_rate", "mrr"}),
    "ragas": frozenset({"faithfulness", "answer_relevancy", "context_precision"}),
}


def _validate_evaluation_metrics(evaluation: EvaluationSettings) -> None:
    """Reject metric/provider combinations that cannot run.

    Only checked when evaluation is enabled: a disabled evaluation block is
    inert, so it should not block loading an otherwise valid configuration.
    """
    if not evaluation.enabled:
        return
    provider = evaluation.provider.strip().lower()
    supported = SUPPORTED_METRICS_BY_PROVIDER.get(provider)
    if supported is None:  # 'none', 'deepeval', custom providers: no contract
        return
    requested = {str(metric).strip().lower() for metric in evaluation.metrics}
    unknown = sorted(requested - supported)
    if unknown:
        raise SettingsError(
            f"evaluation.metrics {unknown} cannot be computed by provider "
            f"'{provider}'. Supported: {sorted(supported)}. "
            "Use provider 'ragas' for generation-quality metrics."
        )


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from a YAML file and validate required fields.

    Args:
        path: Path to settings YAML.  Defaults to
            ``<repo>/config/settings.yaml`` (absolute, CWD-independent).
    """
    settings_path = Path(path) if path is not None else DEFAULT_SETTINGS_PATH
    if not settings_path.is_absolute():
        settings_path = resolve_path(settings_path)
    if not settings_path.exists():
        raise SettingsError(f"Settings file not found: {settings_path}")

    with settings_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    settings = Settings.from_dict(expand_env_vars(data or {}))
    validate_settings(settings)
    return settings