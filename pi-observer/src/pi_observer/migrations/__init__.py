"""Schema migrations for pi_observer.

Import all migration modules here so they register with the runner.
"""

from pi_observer.migrations import m001_simplify_artifacts as m001_simplify_artifacts
from pi_observer.migrations import m002_drop_last_mtime as m002_drop_last_mtime
from pi_observer.migrations import m003_add_fts_index as m003_add_fts_index
from pi_observer.migrations import m004_add_source_column as m004_add_source_column
