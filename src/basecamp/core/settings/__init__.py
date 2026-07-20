"""The unified ``config.json`` layer.

Three modules, one document:
  * :mod:`~basecamp.core.settings.store` — the locked JSON store primitive
    (:class:`Settings`, the :data:`settings` singleton, ``CONFIG_VERSION``);
  * :mod:`~basecamp.core.settings.schema` — the section registry that maps each
    top-level section to its model (from :mod:`basecamp.core.models`) and
    validation policy;
  * :mod:`~basecamp.core.settings.document` — generic dotted-path get/set/unset/
    edit over the registry.

Only the store primitive is re-exported here so that ``from basecamp.core.settings
import settings`` stays valid and import-order-safe (the schema/document modules
pull in the section loaders, so importers reach for them by path). This preserves
every existing ``basecamp.core.settings`` import after the module became a package.
"""

from __future__ import annotations

from basecamp.core.settings.store import CONFIG_VERSION, Settings, settings

__all__ = ["CONFIG_VERSION", "Settings", "settings"]
