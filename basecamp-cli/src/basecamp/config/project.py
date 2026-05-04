"""Project configuration models and loaders for basecamp."""

from pydantic import BaseModel, ConfigDict, Field

from basecamp.settings import settings


class ProjectConfig(BaseModel):
    """Configuration for a single project."""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    additional_dirs: list[str] = Field(default_factory=list)
    description: str = ""
    working_style: str | None = None
    context: str | None = None


def load_projects() -> dict[str, ProjectConfig]:
    """Load project configurations from config.json.

    Returns an empty dict if no projects are configured.
    """
    raw = settings.projects
    if not raw:
        return {}
    return {name: ProjectConfig.model_validate(data) for name, data in raw.items()}


def save_projects(projects: dict[str, ProjectConfig]) -> None:
    """Persist project configurations to config.json."""
    settings.projects = {name: project.model_dump() for name, project in projects.items()}
