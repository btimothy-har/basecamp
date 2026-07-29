from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.terminal_bench import matrix, run

_INPUTS = {
    "models": "glm-5.2",
    "task_set": "docker-amd64",
    "attempts": "1",
    "concurrency": "4",
    "thinking": "per-model",
    "pi_version": "0.80.7",
}


def build(**overrides) -> dict[str, str]:
    return matrix.build_matrix(**{**_INPUTS, **overrides})


def include(**overrides) -> list[dict]:
    return json.loads(build(**overrides)["matrix"])["include"]


def test_amd64_preset_expands_to_five_shards_per_model() -> None:
    entries = include()

    assert [entry["shard"] for entry in entries] == ["1", "2", "3", "long", "mem"]
    assert [entry["preset"] for entry in entries] == [
        "docker-amd64-1",
        "docker-amd64-2",
        "docker-amd64-3",
        "docker-amd64-long",
        "docker-amd64-mem",
    ]
    assert {entry["model"] for entry in entries} == {"openrouter/z-ai/glm-5.2"}


def test_both_models_cross_product_with_shards() -> None:
    entries = include(models="both")

    assert len(entries) == 10
    assert {entry["slug"] for entry in entries} == {"glm-5.2", "kimi-k3"}
    for slug in ("glm-5.2", "kimi-k3"):
        shards = [entry["shard"] for entry in entries if entry["slug"] == slug]
        assert shards == ["1", "2", "3", "long", "mem"]


def test_long_and_mem_shard_concurrency_is_capped_below_short_shards() -> None:
    entries = include(concurrency="4")

    by_shard = {entry["shard"]: entry["concurrency"] for entry in entries}
    assert by_shard["1"] == by_shard["2"] == by_shard["3"] == 4
    assert by_shard["long"] == 3
    assert by_shard["mem"] == 1


def test_shard_caps_never_raise_a_lower_request() -> None:
    by_shard = {entry["shard"]: entry["concurrency"] for entry in include(concurrency="1")}

    assert by_shard["long"] == 1
    assert by_shard["mem"] == 1


def test_shard_timeouts_come_from_the_shard_profiles() -> None:
    by_shard = {entry["shard"]: entry["timeout"] for entry in include()}

    assert by_shard == {"1": 180, "2": 180, "3": 180, "long": 300, "mem": 360}


def test_full_dataset_is_not_sharded() -> None:
    entries = include(task_set="all")

    assert [entry["shard"] for entry in entries] == ["all"]
    assert entries[0]["preset"] == "all"
    assert entries[0]["timeout"] == 360


def test_per_model_thinking_resolves_defaults_and_explicit_level_overrides() -> None:
    assert {entry["thinking"] for entry in include(models="both")} == {"xhigh"}
    assert {entry["thinking"] for entry in include(models="both", thinking="low")} == {"low"}


def test_config_summary_reports_resolved_values() -> None:
    outputs = build(attempts="3", concurrency="2")

    assert outputs["config"] == "docker-amd64 x3 attempts, requested concurrency 2, pi 0.80.7"
    assert outputs["attempts"] == "3"


def test_shard_count_output_matches_the_matrix_size() -> None:
    assert build()["shard-count"] == "5"
    assert build(models="both")["shard-count"] == "10"
    assert build(task_set="all")["shard-count"] == "1"


@pytest.mark.parametrize(
    ("field", "value"),
    [("attempts", "0"), ("attempts", "two"), ("concurrency", "0"), ("concurrency", "-1")],
)
def test_non_positive_counts_are_rejected(field: str, value: str) -> None:
    with pytest.raises(matrix.MatrixInputError, match=field):
        build(**{field: value})


def test_unknown_model_and_bad_pi_version_are_rejected() -> None:
    with pytest.raises(matrix.MatrixInputError, match="unknown models"):
        build(models="gpt-9")
    with pytest.raises(matrix.MatrixInputError, match="x.y.z"):
        build(pi_version="0.80")
    # A trailing newline would corrupt the $GITHUB_OUTPUT key=value line.
    with pytest.raises(matrix.MatrixInputError, match="x.y.z"):
        build(pi_version="0.80.7\n")


def test_unknown_task_set_is_rejected_before_any_paid_setup() -> None:
    with pytest.raises(matrix.MatrixInputError, match="task-set"):
        build(task_set="docker-amd46")


def test_main_appends_github_output_lines(tmp_path: Path) -> None:
    output = tmp_path / "gh-output"
    argv = [
        "--models",
        "glm-5.2",
        "--task-set",
        "docker-amd64",
        "--attempts",
        "1",
        "--concurrency",
        "4",
        "--thinking",
        "per-model",
        "--pi-version",
        "0.80.7",
        "--output",
        str(output),
    ]

    assert matrix.main(argv) == 0

    lines = output.read_text().splitlines()
    keys = [line.split("=", 1)[0] for line in lines]
    assert keys == ["matrix", "attempts", "pi-version", "shard-count", "config"]
    # A GITHUB_OUTPUT value must stay on one line to be parsed: one line per key.
    assert len(lines) == 5


def test_concurrency_is_clamped_to_what_a_shard_can_fill() -> None:
    # A pre-shard request sized for all 34 tasks would otherwise be rejected by
    # the launcher's concurrency-versus-trials check on a ~10-task shard.
    by_shard = {entry["shard"]: entry["concurrency"] for entry in include(concurrency="32")}

    assert by_shard["1"] == 10
    assert by_shard["3"] == 9
    assert by_shard["long"] == 3
    assert by_shard["mem"] == 1


def test_clamp_accounts_for_attempts() -> None:
    by_shard = {entry["shard"]: entry["concurrency"] for entry in include(concurrency="32", attempts="3")}

    assert by_shard["1"] == 30
    assert by_shard["3"] == 27


def test_every_shard_leg_passes_launcher_validation() -> None:
    for entry in include(concurrency="32", attempts="2"):
        options = run.LaunchOptions(
            tasks=run.resolve_tasks((entry["preset"],)),
            engine="docker",
            attempts=2,
            concurrency=entry["concurrency"],
            model=entry["model"],
            thinking=entry["thinking"],
            pi_version="0.80.7",
            models_file=None,
            jobs_dir=Path("/tmp/jobs"),
            install_only=False,
            dry_run=True,
            confirmed=True,
        )
        run.validate_options(options)
