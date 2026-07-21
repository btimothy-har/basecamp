"""Harbor adapter for the Basecamp single-process evaluation profile."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Final, override

from harbor.agents.installed.base import CliFlag
from harbor.agents.installed.node_install import nvm_node_install_snippet
from harbor.agents.installed.pi import Pi
from harbor.environments.base import BaseEnvironment

from . import models as model_config

_PROFILE: Final = "basecamp-pi-single"
_PI_PACKAGE: Final = "@earendil-works/pi-coding-agent"
_NODE_MAJOR: Final = 24
_ARCHIVE_MEMBERS: Final = ("package.json", "package-lock.json", "pi")
_CONTAINER_ARCHIVE: Final = "/tmp/basecamp-eval-source.tar"
_CONTAINER_MODELS: Final = "/tmp/basecamp-eval-models.json"
_CONTAINER_SOURCE: Final = "$HOME/.basecamp-eval/source"
_CONTAINER_METADATA: Final = "/logs/agent/basecamp-eval.json"
_PROFILE_ENV: Final = {
    "BASECAMP_AGENT_DEPTH": "1",
    "BASECAMP_AGENT_MAX_DEPTH": "1",
    "BASECAMP_EXTERNAL_SANDBOX": "1",
}


class BasecampRepositoryNotFoundError(RuntimeError):
    """Configured Basecamp repository does not exist."""

    def __init__(self, repository: Path) -> None:
        super().__init__(f"Basecamp repository does not exist: {repository}")


class BasecampRefRequiredError(RuntimeError):
    """Basecamp evaluation requires a Git revision."""

    def __init__(self) -> None:
        super().__init__("Basecamp evaluation requires a non-empty basecamp_ref")


class PiVersionRequiredError(RuntimeError):
    """Basecamp evaluation requires an exact Pi version."""

    def __init__(self) -> None:
        super().__init__("Basecamp evaluation requires an exact Pi version")


class BasecampSourceError(RuntimeError):
    """Basecamp source revision could not be packaged."""

    def __init__(self, repository: Path, operation: str, detail: str) -> None:
        super().__init__(f"Basecamp source {operation} failed in {repository}: {detail}")


class RuntimeProbeError(RuntimeError):
    """Installed evaluation runtime did not report its versions."""

    def __init__(self, output: str) -> None:
        super().__init__(f"Basecamp evaluation runtime version probe failed: {output!r}")


class ModelAvailabilityError(RuntimeError):
    """Configured model is not available to Pi after setup."""

    def __init__(self, model_name: str) -> None:
        super().__init__(f"Pi model is unavailable after evaluation setup: {model_name}")


def _run_git(repository: Path, operation: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise BasecampSourceError(repository, operation, "git executable not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise BasecampSourceError(repository, operation, detail) from exc
    return result.stdout.strip()


def _resolve_commit(repository: Path, revision: str) -> str:
    if not repository.is_dir():
        raise BasecampRepositoryNotFoundError(repository)
    if not revision.strip():
        raise BasecampRefRequiredError
    return _run_git(repository, "revision resolution", "rev-parse", "--verify", f"{revision}^{{commit}}")


def _create_archive(repository: Path, commit: str, archive: Path) -> str:
    _run_git(
        repository,
        "archive creation",
        "archive",
        "--format=tar",
        f"--output={archive}",
        commit,
        "--",
        *_ARCHIVE_MEMBERS,
    )
    with archive.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class BasecampPiSingle(Pi):
    """Pi with Basecamp's worker-like, single-process surface."""

    CLI_FLAGS = [
        *Pi.CLI_FLAGS,
        CliFlag("unsafe_edit", cli="--unsafe-edit", type="bool", default=True),
        CliFlag(
            "unsafe_edit_sandboxed",
            cli="--unsafe-edit-sandboxed",
            type="bool",
            default=True,
        ),
        CliFlag("exclude_tools", cli="--exclude-tools", default="plan"),
    ]

    def __init__(
        self,
        *args: Any,
        basecamp_repo: str | Path,
        basecamp_ref: str,
        model_name: str | None = None,
        version: str | None = None,
        pi_models_file: str | Path | None = None,
        extra_env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        if version is None or not version.strip():
            raise PiVersionRequiredError

        self._pi_version = version.strip()
        self._basecamp_repository = Path(basecamp_repo).expanduser().resolve()
        self._basecamp_commit = _resolve_commit(self._basecamp_repository, basecamp_ref)
        self._pi_models = (
            model_config.load_pi_models(Path(pi_models_file).expanduser().resolve()) if pi_models_file else None
        )

        profile_env = dict(extra_env or {})
        profile_env.update(model_config.resolve_provider_environment(model_name, profile_env))
        if self._pi_models:
            profile_env.update(model_config.resolve_model_environment(self._pi_models, profile_env))
        self._credential_environment_names = tuple(sorted(set(profile_env) - set(_PROFILE_ENV)))
        profile_env.update(_PROFILE_ENV)
        super().__init__(
            *args,
            model_name=model_name,
            version=self._pi_version,
            extra_env=profile_env,
            **kwargs,
        )

    @staticmethod
    @override
    def name() -> str:
        return _PROFILE

    @override
    def version(self) -> str:
        return f"{self._pi_version}+basecamp.{self._basecamp_commit[:12]}"

    async def _upload_source(self, environment: BaseEnvironment) -> str:
        with tempfile.TemporaryDirectory(prefix="basecamp-eval-") as directory:
            archive = Path(directory) / "source.tar"
            digest = _create_archive(self._basecamp_repository, self._basecamp_commit, archive)
            await environment.upload_file(archive, _CONTAINER_ARCHIVE)
        return digest

    async def _install_models(self, environment: BaseEnvironment) -> None:
        if not self._pi_models:
            return
        with tempfile.TemporaryDirectory(prefix="basecamp-eval-models-") as directory:
            source = Path(directory) / "models.json"
            source.write_bytes(self._pi_models.content)
            await environment.upload_file(source, _CONTAINER_MODELS)
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f"printf '%s  %s\\n' {shlex.quote(self._pi_models.digest)} "
                f"{shlex.quote(_CONTAINER_MODELS)} | sha256sum --check - && "
                'mkdir -p "$HOME/.pi/agent" && '
                f'install --mode 600 {shlex.quote(_CONTAINER_MODELS)} "$HOME/.pi/agent/models.json"'
            ),
        )

    async def _install_pi(self, environment: BaseEnvironment) -> None:
        package = shlex.quote(f"{_PI_PACKAGE}@{self._pi_version}")
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f"{nvm_node_install_snippet(_NODE_MAJOR)} && "
                f"npm install -g --ignore-scripts --no-audit --no-fund {package} && "
                "pi --version"
            ),
        )

    async def _install_basecamp(self, environment: BaseEnvironment, digest: str) -> None:
        archive = shlex.quote(_CONTAINER_ARCHIVE)
        expected_digest = shlex.quote(digest)
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f"printf '%s  %s\\n' {expected_digest} {archive} | sha256sum --check - && "
                f'rm -rf "{_CONTAINER_SOURCE}" && '
                f'mkdir -p "{_CONTAINER_SOURCE}" && '
                "tar --extract --no-same-owner --no-same-permissions "
                f'--file {archive} --directory "{_CONTAINER_SOURCE}" && '
                '. "$HOME/.nvm/nvm.sh" && '
                f'cd "{_CONTAINER_SOURCE}" && '
                "npm ci --omit=dev --ignore-scripts --no-audit --no-fund && "
                f'pi install "{_CONTAINER_SOURCE}"'
            ),
        )

    async def _probe_model(self, environment: BaseEnvironment) -> str:
        if not self.model_name or "/" not in self.model_name:
            raise ModelAvailabilityError(self.model_name or "<missing>")
        provider, model = self.model_name.split("/", 1)
        result = await self.exec_as_agent(
            environment,
            command=(f'. "$HOME/.nvm/nvm.sh"; pi --list-models {shlex.quote(self.model_name)}'),
        )
        for line in (result.stdout or "").splitlines():
            columns = line.split()
            if len(columns) >= 2 and columns[0] == provider and columns[1] == model:
                return self.model_name
        raise ModelAvailabilityError(self.model_name)

    async def _probe_runtime(self, environment: BaseEnvironment) -> dict[str, str]:
        result = await self.exec_as_agent(
            environment,
            command=(
                '. "$HOME/.nvm/nvm.sh"; '
                "printf 'node=%s\\nnpm=%s\\npi=%s\\n' "
                '"$(node --version)" "$(npm --version)" "$(pi --version)"'
            ),
        )
        output = result.stdout or ""
        versions = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if versions.keys() != {"node", "npm", "pi"}:
            raise RuntimeProbeError(output)
        return versions

    async def _upload_metadata(
        self,
        environment: BaseEnvironment,
        digest: str,
        runtime: dict[str, str],
    ) -> None:
        metadata: dict[str, Any] = {
            "profile": _PROFILE,
            "basecamp_commit": self._basecamp_commit,
            "basecamp_archive_sha256": digest,
            "pi_version": self._pi_version,
            "node_major": _NODE_MAJOR,
            "runtime": runtime,
            "model": self.model_name,
            "credential_environment_names": self._credential_environment_names,
            "external_sandbox": True,
            "subagents_enabled": False,
        }
        if self._pi_models:
            metadata["models_config"] = {
                "sha256": self._pi_models.digest,
                "providers": self._pi_models.providers,
                "environment_names": self._pi_models.environment_names,
            }
        with tempfile.TemporaryDirectory(prefix="basecamp-eval-metadata-") as directory:
            path = Path(directory) / "basecamp-eval.json"
            path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
            await environment.upload_file(path, _CONTAINER_METADATA)

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        digest = await self._upload_source(environment)
        await self.exec_as_root(
            environment,
            command="apt-get update && apt-get install -y ca-certificates coreutils curl tar",
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        await self._install_pi(environment)
        await self._install_basecamp(environment, digest)
        await self._install_models(environment)
        await self._probe_model(environment)
        runtime = await self._probe_runtime(environment)
        await self._upload_metadata(environment, digest, runtime)
