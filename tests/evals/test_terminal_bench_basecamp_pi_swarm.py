from __future__ import annotations

import importlib
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


class FakeContext:
    pass


class FakePi:
    CLI_FLAGS = [FakeCliFlag("thinking", "--thinking", type="enum")]

    def __init__(
        self,
        *_args: Any,
        model_name: str | None = None,
        version: str | None = None,
        extra_env: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self._version = version
        self._extra_env = dict(extra_env or {})
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []
        self.run_error: Exception | None = None
        provider, model = (model_name or "/").split("/", 1)
        self.model_output = f"provider model context\n{provider} {model} 128K\n"

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
        if "printf 'node=%s" in command:
            stdout = "node=v24.4.1\nnpm=11.4.2\npi=0.80.7\n"
        elif "pi --list-models" in command:
            stdout = self.model_output
        else:
            stdout = ""
        return types.SimpleNamespace(stdout=stdout)

    async def run(self, instruction: str, _environment: FakeEnvironment, _context: FakeContext) -> None:
        self.calls.append(("run", instruction, None))
        if self.run_error is not None:
            raise self.run_error


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
            "harbor.models",
            "harbor.models.agent",
            "harbor.models.agent.context",
        )
    }
    modules["harbor.agents.installed.base"].CliFlag = FakeCliFlag
    modules["harbor.agents.installed.node_install"].nvm_node_install_snippet = lambda major: f"install-node-{major}"
    modules["harbor.agents.installed.pi"].Pi = FakePi
    modules["harbor.environments.base"].BaseEnvironment = FakeEnvironment
    modules["harbor.models.agent.context"].AgentContext = FakeContext
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def _load_swarm(monkeypatch: pytest.MonkeyPatch):
    _install_harbor_stubs(monkeypatch)
    monkeypatch.syspath_prepend(Path(__file__).resolve().parents[2])
    sys.modules.pop("evals.terminal_bench.basecamp_pi", None)
    sys.modules.pop("evals.terminal_bench.basecamp_pi_swarm", None)
    return importlib.import_module("evals.terminal_bench.basecamp_pi_swarm")


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
    (repository / "src" / "basecamp").mkdir(parents=True)
    (repository / "package.json").write_text('{"name":"basecamp"}\n')
    (repository / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (repository / "pi" / "extension.ts").write_text("export default 'committed';\n")
    (repository / "pyproject.toml").write_text('[project]\nname = "basecamp"\n')
    (repository / "uv.lock").write_text("version = 1\n")
    (repository / "src" / "basecamp" / "__init__.py").write_text("")
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "-m", "committed")
    return repository, _git(repository, "rev-parse", "HEAD")


def _adapter(module: Any, repository: Path, **overrides: Any):
    kwargs: dict[str, Any] = {
        "logs_dir": repository.parent / "logs",
        "basecamp_repo": repository,
        "basecamp_ref": "HEAD",
        "model_name": "openai/gpt-5.6-sol",
        "version": "0.80.7",
    }
    kwargs.update(overrides)
    return module.BasecampPiSwarm(**kwargs)


def test_profile_identity_and_environment(monkeypatch: pytest.MonkeyPatch, source_repository: tuple[Path, str]) -> None:
    module = _load_swarm(monkeypatch)
    repository, _commit = source_repository
    adapter = _adapter(module, repository)

    assert adapter.name() == "basecamp-pi-swarm"
    # Top-level session, one dispatch level, sandbox pair for the launch-flag-rooted
    # propagation. A caller-supplied depth must not demote the session.
    assert adapter.extra_env == {
        "BASECAMP_AGENT_DEPTH": "0",
        "BASECAMP_AGENT_MAX_DEPTH": "1",
        "BASECAMP_EXTERNAL_SANDBOX": "1",
        "BASECAMP_BASH_REVIEWER": "off",
    }
    overridden = _adapter(module, repository, extra_env={"BASECAMP_AGENT_DEPTH": "9"})
    assert overridden.extra_env["BASECAMP_AGENT_DEPTH"] == "0"


def test_archive_adds_python_distribution(
    monkeypatch: pytest.MonkeyPatch,
    source_repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    module = _load_swarm(monkeypatch)
    base = importlib.import_module("evals.terminal_bench.basecamp_pi")
    repository, commit = source_repository
    archive = tmp_path / "source.tar"

    base._create_archive(repository, commit, archive, module.BasecampPiSwarm.ARCHIVE_MEMBERS)
    with tarfile.open(archive) as source:
        names = set(source.getnames())
    assert {"pyproject.toml", "uv.lock", "src", "src/basecamp", "src/basecamp/__init__.py"} <= names
    assert "package.json" in names


@pytest.mark.asyncio
async def test_install_provisions_daemon_and_preflights(
    monkeypatch: pytest.MonkeyPatch, source_repository: tuple[Path, str]
) -> None:
    module = _load_swarm(monkeypatch)
    repository, _commit = source_repository
    adapter = _adapter(module, repository)
    environment = FakeEnvironment()

    await adapter.install(environment)

    roles = [role for role, *_ in adapter.calls]
    assert roles == ["root", "agent", "agent", "agent", "root", "agent", "agent", "agent"]

    commands = [command for _role, command, _env in adapter.calls]
    apt = commands[0]
    assert "git" in apt.split() and "procps" in apt.split()
    uv_sync = commands[3]
    assert '"$HOME/.local/bin/uv" sync --frozen --no-dev' in uv_sync
    assert ".venv/bin/basecamp --help" in uv_sync
    wrapper = commands[4]
    assert "/usr/local/bin/basecamp" in wrapper
    assert "$HOME/.basecamp-eval/source/.venv/bin/basecamp" in wrapper
    preflight = commands[5]
    assert "basecamp hub --uds" in preflight
    assert "http://basecamp/health" in preflight
    assert "exit 1" in preflight


@pytest.mark.asyncio
async def test_metadata_records_swarm_surface(
    monkeypatch: pytest.MonkeyPatch, source_repository: tuple[Path, str]
) -> None:
    module = _load_swarm(monkeypatch)
    repository, commit = source_repository
    adapter = _adapter(module, repository)

    metadata = adapter._build_metadata("digest", {"node": "v24.4.1"})
    assert metadata["profile"] == "basecamp-pi-swarm"
    assert metadata["basecamp_commit"] == commit
    assert metadata["subagents_enabled"] is True
    assert metadata["agent_max_depth"] == 1
    assert metadata["daemon_preflight"] == "passed"
    assert metadata["task_dir_git_init"] == "on-demand"
    assert metadata["task_dir_git_init_size_cap"] == "+50M"
    # Inherited single-profile facts stay recorded.
    assert metadata["external_sandbox"] is True
    assert metadata["bash_reviewer_enabled"] is False


def test_git_init_command_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_swarm(monkeypatch)
    command = module._GIT_INIT_COMMAND

    # Idempotent: an existing repository (a git task, or a resume) is untouched and
    # a prior run's report is preserved.
    assert "git rev-parse --is-inside-work-tree" in command
    assert "[ -f /logs/agent/swarm/git-init.json ] ||" in command
    # Size cap keeps large assets out of the object store via info/exclude.
    assert "-size +50M" in command
    assert ".git/info/exclude" in command
    # The production deliverable posture needs an identity, a branch, and clean HEAD.
    assert "git config --global user.name" in command
    assert "git init --initial-branch=main" in command
    assert "git add -A" in command
    assert "git commit" in command


def test_harvest_command_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_swarm(monkeypatch)
    command = module._HARVEST_COMMAND

    assert "daemon.db" in command
    assert '.pi/basecamp/swarm/agents" /logs/agent/swarm/agents' in command
    assert command.endswith("true")
    assert "set -e" not in command


@pytest.mark.asyncio
async def test_run_inits_repository_then_harvests(
    monkeypatch: pytest.MonkeyPatch, source_repository: tuple[Path, str]
) -> None:
    module = _load_swarm(monkeypatch)
    repository, _commit = source_repository
    adapter = _adapter(module, repository)
    environment = FakeEnvironment()

    await adapter.run("solve the task", environment, FakeContext())

    assert [role for role, *_ in adapter.calls] == ["agent", "run", "agent"]
    assert adapter.calls[0][1] == module._GIT_INIT_COMMAND
    assert adapter.calls[1][1] == "solve the task"
    assert adapter.calls[2][1] == module._HARVEST_COMMAND


@pytest.mark.asyncio
async def test_run_harvests_even_when_the_agent_run_fails(
    monkeypatch: pytest.MonkeyPatch, source_repository: tuple[Path, str]
) -> None:
    module = _load_swarm(monkeypatch)
    repository, _commit = source_repository
    adapter = _adapter(module, repository)
    adapter.run_error = RuntimeError("agent exploded")
    environment = FakeEnvironment()

    with pytest.raises(RuntimeError, match="agent exploded"):
        await adapter.run("solve the task", environment, FakeContext())

    assert adapter.calls[-1][:2] == ("agent", module._HARVEST_COMMAND)


def test_runner_maps_swarm_profile_to_agent_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(Path(__file__).resolve().parents[2])
    run = importlib.import_module("evals.terminal_bench.run")

    options = run.parse_options(["--profile", "swarm", "--dry-run"])
    command = run.build_harbor_command(options, "deadbeef")
    agent = command[command.index("--agent") + 1]
    assert agent == "evals.terminal_bench.basecamp_pi_swarm:BasecampPiSwarm"

    default_options = run.parse_options(["--dry-run"])
    default_command = run.build_harbor_command(default_options, "deadbeef")
    assert default_command[default_command.index("--agent") + 1] == "evals.terminal_bench.basecamp_pi:BasecampPiSingle"
