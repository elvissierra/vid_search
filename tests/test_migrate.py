import pytest

import migrate


def make_dir(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_text("SELECT 1;")
    return tmp_path


def test_discover_orders_by_number(tmp_path):
    make_dir(tmp_path, "002_add_users.sql", "001_baseline.sql", "003_add_quota.sql")
    versions = [version for version, _ in migrate.discover(tmp_path)]
    assert versions == ["001_baseline", "002_add_users", "003_add_quota"]


def test_discover_rejects_misnamed_file(tmp_path):
    make_dir(tmp_path, "001_baseline.sql", "add_users.sql")
    with pytest.raises(ValueError, match="filename"):
        migrate.discover(tmp_path)


def test_discover_rejects_duplicate_number(tmp_path):
    make_dir(tmp_path, "001_baseline.sql", "001_other.sql")
    with pytest.raises(ValueError, match="duplicate"):
        migrate.discover(tmp_path)


def test_discover_rejects_gap(tmp_path):
    make_dir(tmp_path, "001_baseline.sql", "003_add_quota.sql")
    with pytest.raises(ValueError, match="gaps"):
        migrate.discover(tmp_path)


def test_pending_skips_applied(tmp_path):
    make_dir(tmp_path, "001_baseline.sql", "002_add_users.sql")
    discovered = migrate.discover(tmp_path)
    todo = migrate.pending(discovered, {"001_baseline"})
    assert [version for version, _ in todo] == ["002_add_users"]


def test_pending_rejects_unknown_applied(tmp_path):
    make_dir(tmp_path, "001_baseline.sql")
    discovered = migrate.discover(tmp_path)
    with pytest.raises(ValueError, match="missing from this checkout"):
        migrate.pending(discovered, {"001_baseline", "002_from_a_newer_branch"})


def test_shipped_migrations_are_valid():
    """The real migrations/ directory must always pass discovery."""
    assert migrate.discover()[0][0] == "001_baseline"
