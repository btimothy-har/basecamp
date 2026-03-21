"""Schema migrations for observer.

Import all migration modules here so they register with the runner.
"""

from observer.migrations import m001_simplify_artifacts as m001_simplify_artifacts
from observer.migrations import m002_drop_last_mtime as m002_drop_last_mtime
