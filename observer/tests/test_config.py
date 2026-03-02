"""Tests for observer config persistence."""

import json

from observer.services import config


class TestWrite:
    def test_creates_file_with_correct_content(self):
        config._write({"pg_url": "postgresql://localhost/test"})

        assert config.CONFIG_FILE.exists()
        data = json.loads(config.CONFIG_FILE.read_text())
        assert data == {"pg_url": "postgresql://localhost/test"}

    def test_file_permissions_are_owner_only(self):
        config._write({"pg_url": "postgresql://localhost/test"})

        mode = config.CONFIG_FILE.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"

    def test_overwrites_existing_file(self):
        config._write({"pg_url": "postgresql://localhost/first"})
        config._write({"pg_url": "postgresql://localhost/second"})

        data = json.loads(config.CONFIG_FILE.read_text())
        assert data["pg_url"] == "postgresql://localhost/second"

    def test_permissions_preserved_on_overwrite(self):
        config._write({"pg_url": "postgresql://localhost/first"})
        config._write({"pg_url": "postgresql://localhost/second"})

        mode = config.CONFIG_FILE.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"


class TestGetSetPgUrl:
    def test_roundtrip(self):
        config.set_pg_url("postgresql://localhost/obs")
        assert config.get_pg_url() == "postgresql://localhost/obs"

    def test_returns_none_when_not_set(self):
        assert config.get_pg_url() is None


class TestGetSetDbSource:
    def test_roundtrip(self):
        config.set_db_source("container")
        assert config.get_db_source() == "container"

    def test_returns_none_when_not_set(self):
        assert config.get_db_source() is None
