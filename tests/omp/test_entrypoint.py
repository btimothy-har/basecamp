"""Subprocess smoke test for the installed ``bomp`` console script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_bomp_entrypoint_hands_exact_native_arguments_to_omp(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    repo = home / "projects" / "demo"
    nested = repo / "nested"
    shared = home / "projects" / "shared"
    explicit = tmp_path / "explicit"
    _init_repo(repo)
    nested.mkdir()
    shared.mkdir()
    explicit.mkdir()

    config_dir = home / ".pi" / "basecamp"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "install_dir": str(repository_root),
                "projects": {
                    "demo": {
                        "repo_root": "projects/demo",
                        "additional_dirs": ["projects/shared"],
                    }
                },
            }
        )
    )

    config_before = (config_dir / "config.json").read_bytes()
    capture_path = tmp_path / "argv.json"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_omp = fake_bin / "omp"
    fake_omp.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['BOMP_CAPTURE']).write_text(json.dumps(sys.argv))\n"
    )
    fake_omp.chmod(0o755)

    entrypoint = Path(sys.executable).with_name("bomp")
    user_args = [
        "--cwd",
        str(nested),
        f"--add-dir={explicit}",
        "--mode=rpc",
        "--no-session",
    ]
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "BOMP_CAPTURE": str(capture_path),
    }

    result = subprocess.run(
        [str(entrypoint), *user_args],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (config_dir / "config.json").read_bytes() == config_before
    assert json.loads(capture_path.read_text()) == [
        str(fake_omp),
        "--extension",
        str((repository_root / "omp").resolve()),
        f"--add-dir={shared.resolve()}",
        *user_args,
    ]


def test_bomp_entrypoint_reports_missing_omp_without_traceback(tmp_path: Path) -> None:
    entrypoint = Path(sys.executable).with_name("bomp")
    empty_path = tmp_path / "bin"
    empty_path.mkdir()
    env = {**os.environ, "PATH": str(empty_path)}

    result = subprocess.run(
        [str(entrypoint), "--help"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ("bomp: error: OMP executable not found on PATH; install Oh My Pi before using bomp.\n")
