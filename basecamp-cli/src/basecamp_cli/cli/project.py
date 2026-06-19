"""Compatibility exports for interactive project commands.

Project commands are owned by :mod:`basecamp_workspace.cli.project`.
"""

from basecamp_workspace.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
)

__all__ = [
    "execute_project_add",
    "execute_project_edit",
    "execute_project_list",
    "execute_project_remove",
]
