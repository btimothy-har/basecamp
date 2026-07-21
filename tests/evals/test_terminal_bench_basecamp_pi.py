from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
import tarfile
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


@dataclass
class FakeCliFlag:
    kwarg: str
    cli: str
    type: str = "str"
    choices: list[str] | None = None
    default: Any = None


class FakeEnvironment:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str, bytes]] = []

    async def upload_file(self, source_path: Path | str, target_path: str) -> None:
        source = Path(source_path)
        self.uploads.append((source, target_path, source.read_bytes()))


class FakePi:
    CLI_FLAGS = [FakeCliFlag("thinking", "--thinking", type="enum")]

    def __init__(
        self,
        *_args: Any,
        version: str | None = None,
        extra_env: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> None:
        self._version = version
        self._extra_env = dict(extra_env or {})
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []
        self.runtime_output = "node=v24.4.1\nnpm=11.4.2\npi=0.80.7\n"

    @property
    def extra_env(self) -> dict[str, str]:
        return dict(self._extra_env)

    async def exec_as_root(
        self,
        _environment: FakeEnvironment,
        command: str,
        env: dict[str, str] | None = None,
    ) -> types.SimpleNamespace:
        self.calls.append(("root", command, env))
        return types.SimpleNamespace(stdout="")

    async def exec_as_agent(
        self,
        _environment: FakeEnvironment,
        command: str,
        env: dict[str, str] | None = None,
    ) -> types.SimpleNamespace:
        self.calls.append(("agent", command, env))
        stdout = self.runtime_output if "printf 'node=%s" in command else ""
        return types.SimpleNamespace(stdout=stdout)


def _install_harbor_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {
        name: types.ModuleType(name)
        for name in (
            "harbor",
            "harbor.agents",
            "harbor.agents.installed",
            "harbor.agents.installed.base",
            "harbor.agents.installed.node_install",
            "harbor.agents.installed.pi",
            "harbor.environments",
            "harbor.environments.base",
        )
    }
    modules["harbor.agents.installed.base"].CliFlag = FakeCliFlag
    modules["harbor.agents.installed.node_install"].nvm_node_install_snippet = lambda major: f"install-node-{major}"
    modules["harbor.agents.installed.pi"].Pi = FakePi
    modules["harbor.environments.base"].BaseEnvironment = FakeEnvironment
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def _load_adapter(monkeypatch: pytest.MonkeyPatch):
    _install_harbor_stubs(monkeypatch)
    monkeypatch.syspath_prepend(Path(__file__).resolve().parents[2])
    sys.modules.pop("evals.terminal_bench.basecamp_pi", None)
    return importlib.import_module("evals.terminal_bench.basecamp_pi")


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def source_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "basecamp"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "eval@example.com")
    _git(repository, "config", "user.name", "Eval Test")

    (repository / "pi").mkdir()
    (repository / "package.json").write_text('{"name":"basecamp"}\n')
    (repository / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (repository / "pi" / "extension.ts").write_text("export default 'committed';\n")
    (repository / "python-secret.txt").write_text("not part of the Pi package\n")
    _git(repository, "add", "package.json", "package-lock.json", "pi/extension.ts", "python-secret.txt")
    _git(repository, "commit", "--quiet", "-m", "fixture")
    commit = _git(repository, "rev-parse", "HEAD")

    (repository / "pi" / "extension.ts").write_text("export default 'dirty';\n")
    (repository / "untracked-secret.txt").write_text("must not be archived\n")
    return repository, commit


def test_archive_contains_only_committed_pi_package(
    monkeypatch: pytest.MonkeyPatch,
    source_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    adapter = _load_adapter(monkeypatch)
    repository, commit = source_repository
    archive = tmp_path / "source.tar"

    assert adapter._resolve_commit(repository, "HEAD") == commit
    digest = adapter._create_archive(repository, commit, archive)

    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    with tarfile.open(archive) as source:
        assert set(source.getnames()) == {
            "package.json",
            "package-lock.json",
            "pi",
            "pi/extension.ts",
        }
        extension = source.extractfile("pi/extension.ts")
        assert extension is not None
        assert extension.read() == b"export default 'committed';\n"


def test_profile_identity_flags_and_environment(
    monkeypatch: pytest.MonkeyPatch,
    source_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    adapter = _load_adapter(monkeypatch)
    repository, commit = source_repository

    agent = adapter.BasecampPiSingle(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-sol",
        basecamp_repo=repository,
        basecamp_ref="HEAD",
        version="0.80.7",
        extra_env={"KEEP": "yes", "BASECAMP_AGENT_DEPTH": "9"},
    )

    assert agent.name() == "basecamp-pi-single"
    assert agent.version() == f"0.80.7+basecamp.{commit[:12]}"
    assert agent.extra_env == {
        "KEEP": "yes",
        "BASECAMP_AGENT_DEPTH": "1",
        "BASECAMP_AGENT_MAX_DEPTH": "1",
        "BASECAMP_EXTERNAL_SANDBOX": "1",
    }
    flags = {flag.kwarg: flag for flag in agent.CLI_FLAGS}
    assert flags["unsafe_edit"].default is True
    assert flags["unsafe_edit_sandboxed"].default is True
    assert flags["exclude_tools"].default == "plan"


def test_configuration_guards_fail_before_setup(
    monkeypatch: pytest.MonkeyPatch,
    source_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    adapter = _load_adapter(monkeypatch)
    repository, _ = source_repository
    common = {"logs_dir": tmp_path, "model_name": "openai/gpt-5.6-sol"}

    with pytest.raises(adapter.PiVersionRequiredError):
        adapter.BasecampPiSingle(
            **common,
            basecamp_repo=repository,
            basecamp_ref="HEAD",
            version=" ",
        )
    with pytest.raises(adapter.BasecampRefRequiredError):
        adapter.BasecampPiSingle(
            **common,
            basecamp_repo=repository,
            basecamp_ref="",
            version="0.80.7",
        )
    with pytest.raises(adapter.BasecampRepositoryNotFoundError):
        adapter.BasecampPiSingle(
            **common,
            basecamp_repo=tmp_path / "missing",
            basecamp_ref="HEAD",
            version="0.80.7",
        )
    with pytest.raises(adapter.BasecampSourceError):
        adapter.BasecampPiSingle(
            **common,
            basecamp_repo=repository,
            basecamp_ref="missing-ref",
            version="0.80.7",
        )


@pytest.mark.asyncio
async def test_install_uploads_auditable_source_and_uses_task_user(
    monkeypatch: pytest.MonkeyPatch,
    source_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    adapter = _load_adapter(monkeypatch)
    repository, commit = source_repository
    environment = FakeEnvironment()
    agent = adapter.BasecampPiSingle(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-sol",
        basecamp_repo=repository,
        basecamp_ref=commit,
        version="0.80.7",
    )

    await agent.install(environment)

    assert [target for _, target, _ in environment.uploads] == [
        "/tmp/basecamp-eval-source.tar",
        "/logs/agent/basecamp-eval.json",
    ]
    archive_path, _, archive_bytes = environment.uploads[0]
    metadata_path, _, metadata_bytes = environment.uploads[1]
    assert archive_path != metadata_path

    metadata = json.loads(metadata_bytes)
    assert metadata == {
        "basecamp_archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "basecamp_commit": commit,
        "external_sandbox": True,
        "node_major": 24,
        "pi_version": "0.80.7",
        "profile": "basecamp-pi-single",
        "runtime": {"node": "v24.4.1", "npm": "11.4.2", "pi": "0.80.7"},
        "subagents_enabled": False,
    }

    assert [kind for kind, _, _ in agent.calls] == ["root", "agent", "agent", "agent"]
    root_command = agent.calls[0][1]
    pi_command = agent.calls[1][1]
    basecamp_command = agent.calls[2][1]
    digest = hashlib.sha256(archive_bytes).hexdigest()
    assert agent.calls[0][2] == {"DEBIAN_FRONTEND": "noninteractive"}
    assert "apt-get install -y ca-certificates coreutils curl tar" in root_command
    assert "install-node-24" in pi_command
    assert "@earendil-works/pi-coding-agent@0.80.7" in pi_command
    assert "sha256sum --check" in basecamp_command
    assert digest in basecamp_command
    assert "npm ci --omit=dev --ignore-scripts --no-audit --no-fund" in basecamp_command
    assert 'pi install "$HOME/.basecamp-eval/source"' in basecamp_command


@pytest.mark.asyncio
async def test_runtime_probe_rejects_incomplete_output(
    monkeypatch: pytest.MonkeyPatch,
    source_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    adapter = _load_adapter(monkeypatch)
    repository, commit = source_repository
    agent = adapter.BasecampPiSingle(
        logs_dir=tmp_path,
        model_name="openai/gpt-5.6-sol",
        basecamp_repo=repository,
        basecamp_ref=commit,
        version="0.80.7",
    )
    agent.runtime_output = "node=v24.4.1\n"

    with pytest.raises(adapter.RuntimeProbeError):
        await agent._probe_runtime(FakeEnvironment())
