"""Project configuration models and loaders for basecamp."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from basecamp.exceptions import ProjectNotFoundError
from basecamp.settings import settings


class BigQueryConfig(BaseModel):
    """Optional BigQuery convenience defaults for query tooling."""

    model_config = ConfigDict(extra="allow")

    enabled: bool | None = None
    default_project_id: str | None = None
    default_location: str | None = None
    default_output_format: Literal["csv", "json"] | None = None
    default_max_rows: int | None = None
    auto_dry_run: bool | None = None


class ProjectConfig(BaseModel):
    """Configuration for a single project."""

    dirs: list[str]
    description: str = ""
    working_style: str | None = None
    context: str | None = None
    bigquery: BigQueryConfig | None = None


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


def _dump_project(project: ProjectConfig) -> dict[str, Any]:
    """Serialize a project while omitting absent BigQuery config."""
    data = project.model_dump()
    if project.bigquery is None:
        data.pop("bigquery", None)
    else:
        data["bigquery"] = project.bigquery.model_dump(exclude_none=True)
    return data


def save_projects(projects: dict[str, ProjectConfig]) -> None:
    """Persist project configurations to config.json."""
    settings.projects = {name: _dump_project(project) for name, project in projects.items()}
