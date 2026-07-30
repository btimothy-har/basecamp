"""Pi model-proxy configuration for isolated Terminal-Bench trials."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Final, NamedTuple

_ENV_REFERENCE: Final = re.compile(r"(?<!\$)\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
_SENSITIVE_HEADERS: Final = {"authorization", "proxy-authorization", "x-api-key", "api-key"}
_STANDARD_PROVIDER_ENV: Final = {
    "amazon-bedrock": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN"),
    "github-copilot": ("GITHUB_TOKEN",),
    "google": (
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_API_KEY",
    ),
    "groq": ("GROQ_API_KEY",),
    "huggingface": ("HF_TOKEN",),
    "mistral": ("MISTRAL_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "xai": ("XAI_API_KEY",),
}


class PiModelsFileError(RuntimeError):
    """Pi models configuration cannot be copied safely."""

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"Invalid Pi models configuration at {path}: {detail}")


class PiModelsEnvironmentError(RuntimeError):
    """A models.json environment reference is unavailable."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(f"Missing environment variables referenced by Pi models.json: {', '.join(names)}")


class PiModelsSnapshot(NamedTuple):
    content: bytes
    digest: str
    providers: tuple[str, ...]
    environment_names: tuple[str, ...]


def _environment_references(value: str) -> set[str]:
    return {braced or plain for braced, plain in _ENV_REFERENCE.findall(value)}


def load_pi_models(path: Path) -> PiModelsSnapshot:
    if not path.is_file():
        raise PiModelsFileError(path, "file does not exist")
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PiModelsFileError(path, "invalid JSON") from exc
    if not isinstance(document, dict) or not isinstance(document.get("providers"), dict):
        raise PiModelsFileError(path, "top-level providers object is required")

    environment_names: set[str] = set()
    for provider_name, config in document["providers"].items():
        if not isinstance(provider_name, str) or not isinstance(config, dict):
            raise PiModelsFileError(path, "provider entries must be named objects")
        api_key = config.get("apiKey")
        if api_key is not None:
            if not isinstance(api_key, str) or api_key.startswith("!"):
                raise PiModelsFileError(path, f"{provider_name}.apiKey must use environment interpolation")
            references = _environment_references(api_key)
            if not references:
                raise PiModelsFileError(path, f"{provider_name}.apiKey must use environment interpolation")
            environment_names.update(references)
        headers = config.get("headers")
        if headers is None:
            continue
        if not isinstance(headers, dict):
            raise PiModelsFileError(path, f"{provider_name}.headers must be an object")
        for header_name, value in headers.items():
            if not isinstance(header_name, str) or not isinstance(value, str) or value.startswith("!"):
                raise PiModelsFileError(path, f"{provider_name}.headers contains an unsupported value")
            references = _environment_references(value)
            if header_name.lower() in _SENSITIVE_HEADERS and not references:
                raise PiModelsFileError(path, f"{provider_name}.{header_name} must use environment interpolation")
            environment_names.update(references)

    return PiModelsSnapshot(
        content=content,
        digest=hashlib.sha256(content).hexdigest(),
        providers=tuple(sorted(document["providers"])),
        environment_names=tuple(sorted(environment_names)),
    )


def resolve_model_environment(
    snapshot: PiModelsSnapshot,
    configured: dict[str, str],
) -> dict[str, str]:
    missing: list[str] = []
    resolved: dict[str, str] = {}
    for name in snapshot.environment_names:
        value = configured.get(name) or os.environ.get(name)
        if not value:
            missing.append(name)
        else:
            resolved[name] = value
    if missing:
        raise PiModelsEnvironmentError(missing)
    return resolved


def resolve_provider_environment(model_name: str | None, configured: dict[str, str]) -> dict[str, str]:
    if not model_name or "/" not in model_name:
        return {}
    provider = model_name.split("/", 1)[0]
    resolved: dict[str, str] = {}
    for name in _STANDARD_PROVIDER_ENV.get(provider, ()):
        value = configured.get(name) or os.environ.get(name)
        if value:
            resolved[name] = value
    return resolved
