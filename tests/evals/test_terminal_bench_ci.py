from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.terminal_bench import models, summarize

_TEMPLATE = {
    "providers": {
        "openrouter": {
            "baseUrl": "$BIFROST_BASE_URL/v1",
            "apiKey": "$LLM_API_KEY",
            "api": "openai-completions",
            "models": [{"id": "z-ai/glm-5.2", "contextWindow": 1000000, "maxTokens": 130000}],
        }
    }
}


def _write_template(tmp_path: Path) -> Path:
    source = tmp_path / "models.template.json"
    source.write_text(json.dumps(_TEMPLATE))
    return source


def test_render_models_template_resolves_base_url_only(tmp_path: Path) -> None:
    source = _write_template(tmp_path)
    destination = tmp_path / "rendered.json"

    snapshot = models.render_models_template(source, destination, {"BIFROST_BASE_URL": "https://proxy.example.test"})

    rendered = json.loads(destination.read_text())
    provider = rendered["providers"]["openrouter"]
    assert provider["baseUrl"] == "https://proxy.example.test/v1"
    assert provider["apiKey"] == "$LLM_API_KEY"
    assert snapshot.environment_names == ("LLM_API_KEY",)


def test_render_models_template_fails_on_unresolved_placeholder(tmp_path: Path) -> None:
    source = _write_template(tmp_path)

    with pytest.raises(models.PiModelsRenderError, match="BIFROST_BASE_URL"):
        models.render_models_template(source, tmp_path / "rendered.json", {})


def _job_result(**overrides) -> dict:
    result = {
        "id": "job-1",
        "n_total_trials": 3,
        "stats": {
            "n_completed_trials": 3,
            "n_errored_trials": 0,
            "n_pending_trials": 0,
            "n_running_trials": 0,
            "n_cancelled_trials": 0,
            "cost_usd": 1.5,
            "evals": {"agent__model__dataset": {"metrics": [{"mean": 0.75}]}},
        },
    }
    result["stats"].update(overrides)
    return result


def _write_job(jobs_dir: Path, name: str, result: dict) -> Path:
    job_dir = jobs_dir / name
    job_dir.mkdir(parents=True)
    path = job_dir / "result.json"
    path.write_text(json.dumps(result))
    return path


def test_find_job_result_ignores_trial_level_files(tmp_path: Path) -> None:
    job_result = _write_job(tmp_path, "job-a", _job_result())
    trial_dir = tmp_path / "job-a" / "task__abc1234"
    trial_dir.mkdir()
    trial_result = trial_dir / "result.json"
    trial_result.write_text(json.dumps({"task_name": "task"}))

    assert summarize.find_job_result(tmp_path) == job_result


def test_build_summary_projects_scores_and_completeness(tmp_path: Path) -> None:
    path = _write_job(tmp_path, "job-a", _job_result())

    lines, complete = summarize.build_summary(json.loads(path.read_text()), path)

    table = "\n".join(lines)
    assert "agent__model__dataset | 0.7500" in table
    assert "n_total_trials | 3" in table
    assert "cost_usd | 1.5000" in table
    assert complete is True


def test_build_summary_flags_incomplete_jobs(tmp_path: Path) -> None:
    path = _write_job(tmp_path, "job-a", _job_result(n_pending_trials=2, n_cancelled_trials=1))

    lines, complete = summarize.build_summary(json.loads(path.read_text()), path)

    assert any("incomplete" in line for line in lines)
    assert complete is False


def test_summarize_main_reports_missing_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert summarize.main([str(tmp_path)]) == 1
    assert "No job-level result.json" in capsys.readouterr().out
