import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PORTABLE_SKILLS = (
    "data-analysis",
    "data-warehousing",
    "marimo",
    "python-development",
    "sql",
)


def test_portable_skills_are_owned_by_pi_package() -> None:
    for skill in _PORTABLE_SKILLS:
        assert (_REPO_ROOT / "pi" / "skills" / skill).is_dir()

    assert not (_REPO_ROOT / "omp" / "skills").exists()

    manifest = json.loads((_REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    skill_roots = manifest["pi"]["skills"]

    assert "./pi/skills" in skill_roots
    assert "./omp/skills" not in skill_roots
