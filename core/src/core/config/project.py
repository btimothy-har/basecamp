"""Project configuration models and loaders for basecamp."""

from pydantic import BaseModel

from core.exceptions import ProjectNotFoundError
from core.settings import settings


class ProjectConfig(BaseModel):
    """Configuration for a single project."""

    dirs: list[str]
    description: str = ""
    working_style: str | None = None
    context: str | None = None


class Config(BaseModel):
    """Root configuration containing all projects."""

    projects: dict[str, ProjectConfig]


def resolve_project(project_name: str, config: Config) -> ProjectConfig:
    """Resolve a project name to its configuration.

    Args:
        project_name: The project name to resolve.
        config: The loaded configuration containing user projects.

    Returns:
        The ProjectConfig for the requested project.

    Raises:
        ProjectNotFoundError: If the project is not found.
    """
    if project_name in config.projects:
        return config.projects[project_name]
    raise ProjectNotFoundError(project_name, list(config.projects.keys()))


def load_config() -> Config:
    """Load project configuration from config.json.

    Returns an empty config if no projects are configured.
    """
    projects = settings.projects
    if not projects:
        return Config(projects={})
    return Config.model_validate({"projects": projects})


def save_config(config: Config) -> None:
    """Persist project configuration to config.json."""
    settings.projects = config.model_dump()["projects"]
