"""Pi model-proxy configuration for isolated Terminal-Bench trials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
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


class PiModelsRenderError(RuntimeError):
    """A models template cannot be rendered into a runnable configuration."""

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"Cannot render Pi models template at {path}: {detail}")


def _render_base_url(source: Path, provider: str, value: str, environment: Mapping[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        resolved = environment.get(name)
        if not resolved:
            raise PiModelsRenderError(source, f"{provider}.baseUrl: environment variable is unavailable: {name}")
        return resolved

    return _ENV_REFERENCE.sub(substitute, value)


def render_models_template(
    source: Path,
    destination: Path,
    environment: Mapping[str, str] | None = None,
) -> PiModelsSnapshot:
    """Resolve provider baseUrl env references, leaving credential references for Pi.

    Pi interpolates $VAR templates in apiKey and headers only, so a template that
    keeps its base URL out of the repository must be rendered before launch.
    """
    env = environment if environment is not None else os.environ
    snapshot = load_pi_models(source)
    document = json.loads(snapshot.content)
    for provider_name, config in document["providers"].items():
        base_url = config.get("baseUrl")
        if isinstance(base_url, str):
            config["baseUrl"] = _render_base_url(source, provider_name, base_url, env)
    rendered = (json.dumps(document, indent=2) + "\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(rendered)
    return load_pi_models(destination)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a Pi models template for evaluation runs")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        snapshot = render_models_template(args.source.expanduser(), args.destination.expanduser())
    except (PiModelsFileError, PiModelsRenderError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"Rendered {args.source} -> {args.destination} (sha256 {snapshot.digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
