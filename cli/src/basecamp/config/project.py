"""Project configuration models and loaders for basecamp."""

from pydantic import BaseModel

from basecamp.exceptions import ProjectNotFoundError
from basecamp.settings import settings


class ProjectConfig(BaseModel):
    """Configuration for a single project."""

    dirs: list[str]
    description: str = ""
    working_style: str | None = None
    context: str | None = None


def resolve_project(project_name: str, projects: dict[str, ProjectConfig]) -> ProjectConfig:
    """Resolve a project name to its configuration.

    Args:
        project_name: The project name to resolve.
        projects: Dict of project name → config.

    Returns:
        The ProjectConfig for the requested project.

    Raises:
        ProjectNotFoundError: If the project is not found.
    """
    if project_name in projects:
        return projects[project_name]
    raise ProjectNotFoundError(project_name, list(projects.keys()))


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
    settings.projects = {name: p.model_dump() for name, p in projects.items()}
