from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.terminal_bench import summarize


def _harbor_result(
    *,
    passes: int,
    fails: int,
    errored_scored: int = 0,
    errored_unscored: int = 0,
    cost: float = 1.5,
    eval_key: str = "agent__model__dataset",
    **stat_overrides,
) -> dict:
    """A job result in harbor's real shape.

    Errored trials are a subset of completed trials, and an errored trial the
    verifier still reached occupies a reward bucket (usually at 0.0). Only
    trials the verifier never reached are absent from the buckets — that is
    the one coverage gap harbor can emit.
    """
    completed = passes + fails + errored_scored + errored_unscored
    zeros = [f"fail-{index}" for index in range(fails)] + [f"err-{index}" for index in range(errored_scored)]
    result = {
        "id": "job-1",
        "n_total_trials": completed,
        "stats": {
            "n_completed_trials": completed,
            "n_errored_trials": errored_scored + errored_unscored,
            "n_pending_trials": 0,
            "n_running_trials": 0,
            "n_cancelled_trials": 0,
            "cost_usd": cost,
            "evals": {
                eval_key: {
                    "metrics": [{"mean": passes / completed if completed else 0.0}],
                    "reward_stats": {
                        "reward": {
                            "1.0": [f"pass-{index}" for index in range(passes)],
                            "0.0": zeros,
                        }
                    },
                }
            },
        },
    }
    result["stats"].update(stat_overrides)
    return result


def _write_job(jobs_dir: Path, name: str, result: dict) -> Path:
    job_dir = jobs_dir / name
    job_dir.mkdir(parents=True)
    path = job_dir / "result.json"
    path.write_text(json.dumps(result))
    return path


def test_find_job_result_ignores_trial_level_files(tmp_path: Path) -> None:
    job_result = _write_job(tmp_path, "job-a", _harbor_result(passes=2, fails=1))
    trial_dir = tmp_path / "job-a" / "task__abc1234"
    trial_dir.mkdir()
    trial_result = trial_dir / "result.json"
    trial_result.write_text(json.dumps({"task_name": "task"}))

    assert summarize.find_job_result(tmp_path) == job_result


def test_build_summary_projects_scores_and_completeness(tmp_path: Path) -> None:
    path = _write_job(tmp_path, "job-a", _harbor_result(passes=3, fails=1))

    lines, complete = summarize.build_summary(json.loads(path.read_text()), path)

    table = "\n".join(lines)
    assert "agent__model__dataset | 0.7500" in table
    assert "n_total_trials | 4" in table
    assert "n_scored_trials | 4" in table
    assert "cost_usd | 1.5000" in table
    assert complete is True


def test_build_summary_flags_incomplete_jobs(tmp_path: Path) -> None:
    path = _write_job(tmp_path, "job-a", _harbor_result(passes=3, fails=1, n_pending_trials=2, n_cancelled_trials=1))

    lines, complete = summarize.build_summary(json.loads(path.read_text()), path)

    assert any("incomplete" in line for line in lines)
    assert complete is False


def test_build_summary_treats_scored_errored_trials_as_complete(tmp_path: Path) -> None:
    # An agent crash the verifier still scored (at 0.0) is an ordinary
    # capability outcome: warn, but stay green.
    _write_job(tmp_path, "job-a", _harbor_result(passes=1, fails=1, errored_scored=2))
    path = tmp_path / "job-a" / "result.json"

    lines, complete = summarize.build_summary(json.loads(path.read_text()), path)

    assert any("2 errored trial(s)" in line and "count toward the mean" in line for line in lines)
    assert not any("without a score" in line for line in lines)
    assert complete is True
    assert summarize.main([str(tmp_path)]) == 0


def test_build_summary_flags_trials_the_verifier_never_scored(tmp_path: Path) -> None:
    _write_job(tmp_path, "job-a", _harbor_result(passes=2, fails=0, errored_unscored=1))
    path = tmp_path / "job-a" / "result.json"

    lines, complete = summarize.build_summary(json.loads(path.read_text()), path)

    assert any("1 trial(s) finished without a score" in line for line in lines)
    assert "n_scored_trials | 2" in "\n".join(lines)
    assert complete is False
    assert summarize.main([str(tmp_path)]) == 1


def test_build_summary_skips_malformed_reward_stats(tmp_path: Path) -> None:
    result = _harbor_result(passes=2, fails=0)
    result["stats"]["evals"]["null_stats"] = {"reward_stats": None}
    result["stats"]["evals"]["bad_key"] = {"reward_stats": {"reward": {"not-a-number": ["t"]}}}
    result["stats"]["evals"]["bad_bucket"] = {"reward_stats": {"reward": {"1.0": 3}}}
    path = _write_job(tmp_path, "job-a", result)

    lines, complete = summarize.build_summary(json.loads(path.read_text()), path)

    assert "n_scored_trials | 2" in "\n".join(lines)
    assert complete is True


def test_summarize_main_reports_missing_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert summarize.main([str(tmp_path)]) == 1
    assert "No job-level result.json" in capsys.readouterr().out


_EVAL_KEY = "agent__model__dataset"


def _pool(tmp_path: Path) -> dict:
    return summarize.pool_results(summarize.find_shard_results(tmp_path))


def test_pooled_score_weights_shards_by_trial_count(tmp_path: Path) -> None:
    _write_job(tmp_path / "shard-1", "job", _harbor_result(passes=7, fails=3, cost=2.0))
    _write_job(tmp_path / "shard-long", "job", _harbor_result(passes=1, fails=4, cost=0.5))

    pooled = _pool(tmp_path)

    # 8 passes over 15 scored trials. Averaging the shards' own means would give
    # (0.7 + 0.2) / 2 = 0.45, which is wrong for unequal shard sizes.
    assert pooled["evals"][_EVAL_KEY]["score"] == pytest.approx(8 / 15)
    assert pooled["evals"][_EVAL_KEY]["score"] != pytest.approx(0.45)
    assert pooled["evals"][_EVAL_KEY]["n_scored"] == 15
    assert pooled["n_scored_trials"] == 15
    assert pooled["n_total_trials"] == 15
    assert pooled["cost_usd"] == pytest.approx(2.5)


def test_pooled_scores_stay_separated_per_eval_key(tmp_path: Path) -> None:
    # The eval key embeds the model, so pooling across keys would blend two
    # model legs into one unattributable number.
    _write_job(tmp_path / "shard-1", "job", _harbor_result(passes=4, fails=0, eval_key="agent__glm__dataset"))
    _write_job(tmp_path / "shard-2", "job", _harbor_result(passes=0, fails=4, eval_key="agent__kimi__dataset"))

    pooled = _pool(tmp_path)
    lines, complete = summarize.build_pooled_summary(pooled, shards=2)

    assert pooled["evals"]["agent__glm__dataset"]["score"] == pytest.approx(1.0)
    assert pooled["evals"]["agent__kimi__dataset"]["score"] == pytest.approx(0.0)
    table = "\n".join(lines)
    assert "agent__glm__dataset | 1.0000" in table
    assert "agent__kimi__dataset | 0.0000" in table
    assert "0.5000" not in table
    assert complete is True


def test_pooled_results_ignore_trial_level_files(tmp_path: Path) -> None:
    _write_job(tmp_path / "shard-1", "job", _harbor_result(passes=2, fails=0))
    trial = tmp_path / "shard-1" / "job" / "task__abc1234"
    trial.mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({"task_name": "task", "agent_result": {}}))

    results = summarize.find_shard_results(tmp_path)

    assert len(results) == 1
    assert summarize.pool_results(results)["n_scored_trials"] == 2


def test_pooled_summary_treats_scored_errored_trials_as_complete(tmp_path: Path) -> None:
    _write_job(tmp_path / "shard-1", "job", _harbor_result(passes=3, fails=0))
    _write_job(tmp_path / "shard-2", "job", _harbor_result(passes=1, fails=1, errored_scored=2))

    pooled = _pool(tmp_path)
    lines, complete = summarize.build_pooled_summary(pooled, shards=2)

    assert pooled["n_errored_trials"] == 2
    assert any("2 errored trial(s)" in line and "count toward the mean" in line for line in lines)
    assert complete is True
    assert summarize.main([str(tmp_path), "--pooled"]) == 0


def test_pooled_summary_fails_on_a_coverage_gap(tmp_path: Path) -> None:
    _write_job(tmp_path / "shard-1", "job", _harbor_result(passes=3, fails=0))
    _write_job(tmp_path / "shard-2", "job", _harbor_result(passes=1, fails=1, errored_unscored=2))

    lines, complete = summarize.build_pooled_summary(_pool(tmp_path), shards=2)

    assert any("2 trial(s) finished without a score" in line for line in lines)
    assert complete is False
    assert summarize.main([str(tmp_path), "--pooled"]) == 1


def test_pooled_summary_fails_when_a_shard_artifact_is_missing(tmp_path: Path) -> None:
    _write_job(tmp_path / "shard-1", "job", _harbor_result(passes=3, fails=1))
    _write_job(tmp_path / "shard-2", "job", _harbor_result(passes=2, fails=0))

    lines, complete = summarize.build_pooled_summary(_pool(tmp_path), shards=2, expected_shards=3)

    assert any("Expected 3 shard result(s) but found 2" in line for line in lines)
    assert complete is False
    assert summarize.main([str(tmp_path), "--pooled", "--expected-shards", "3"]) == 1
    assert summarize.main([str(tmp_path), "--pooled", "--expected-shards", "2"]) == 0


def test_pooled_summary_skips_malformed_reward_stats(tmp_path: Path) -> None:
    result = _harbor_result(passes=2, fails=0)
    result["stats"]["evals"]["null_stats"] = {"reward_stats": None}
    result["stats"]["evals"]["bad_key"] = {"reward_stats": {"reward": {"not-a-number": ["t"]}}}
    result["stats"]["evals"]["bad_bucket"] = {"reward_stats": {"reward": {"1.0": 3}}}
    _write_job(tmp_path / "shard-1", "job", result)

    pooled = _pool(tmp_path)

    assert pooled["evals"][_EVAL_KEY]["n_scored"] == 2
    assert pooled["n_scored_trials"] == 2
    assert summarize.main([str(tmp_path), "--pooled"]) == 0


def test_pooled_summary_reports_missing_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert summarize.main([str(tmp_path), "--pooled"]) == 1
    assert "No job-level result.json" in capsys.readouterr().out


def test_pooled_summary_succeeds_on_clean_shards(tmp_path: Path) -> None:
    _write_job(tmp_path / "shard-1", "job", _harbor_result(passes=3, fails=1))
    _write_job(tmp_path / "shard-2", "job", _harbor_result(passes=2, fails=0))

    assert summarize.main([str(tmp_path), "--pooled"]) == 0
