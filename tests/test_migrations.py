"""tests/test_migrations.py — H5 strict migration error handling.

Проверяет _run_migrations:
  • duplicate column → skip без raise (логирует DEBUG);
  • CREATE INDEX IF NOT EXISTS на повтор → skip;
  • SQL syntax error → re-raise OperationalError;
  • ALTER на несуществующую таблицу → re-raise OperationalError.

Адаптация под Flaka: миграции живут в `db/migrations.py` (`MIGRATIONS`-лист,
единый источник правды), а `db/connection.py:_run_migrations` итерирует по
этому списку. Вместо хитрых монки-патчей кодовых объектов мы патчим список
`db.migrations.MIGRATIONS` через monkeypatch и вызываем _run_migrations
напрямую с in-memory соединением.
"""
import sqlite3

import pytest

from db.connection import _run_migrations


def _bootstrap_db():
    """Минимальная схема: одна таблица, на которую можно alter'ить."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE foo (id INTEGER PRIMARY KEY, name TEXT)"
    )
    conn.commit()
    return conn


def test_duplicate_column_is_skipped(monkeypatch):
    """Дубликат ALTER ADD COLUMN не должен падать (skip + continue)."""
    conn = _bootstrap_db()
    # Эмулируем что миграция уже применена ранее.
    conn.execute("ALTER TABLE foo ADD COLUMN extra TEXT")
    conn.commit()

    fake_migrations = [
        "ALTER TABLE foo ADD COLUMN extra TEXT",  # дубликат — должно быть skip
    ]
    monkeypatch.setattr("db.migrations.MIGRATIONS", fake_migrations)

    # Не должно поднимать никаких исключений.
    _run_migrations(conn)


def test_index_already_exists_is_skipped(monkeypatch):
    """CREATE INDEX IF NOT EXISTS на повтор не должен падать."""
    conn = _bootstrap_db()
    # Создаём индекс заранее.
    conn.execute("CREATE INDEX idx_foo_name ON foo(name)")
    conn.commit()

    fake_migrations = [
        # Без IF NOT EXISTS — sqlite ругнётся "already exists".
        "CREATE INDEX idx_foo_name ON foo(name)",
    ]
    monkeypatch.setattr("db.migrations.MIGRATIONS", fake_migrations)

    # Сообщение SQLite содержит "already exists" → должно быть skip.
    _run_migrations(conn)


def test_run_migrations_passes_when_only_duplicates(monkeypatch):
    """Полный _run_migrations с already-applied миграциями не падает."""
    conn = _bootstrap_db()
    conn.execute("ALTER TABLE foo ADD COLUMN extra TEXT")
    conn.commit()

    fake_migrations = [
        "ALTER TABLE foo ADD COLUMN extra TEXT",          # дубликат
        "CREATE INDEX IF NOT EXISTS idx_foo_name ON foo(name)",  # ok
        "CREATE INDEX IF NOT EXISTS idx_foo_name ON foo(name)",  # повтор IF NOT EXISTS — ok
    ]
    monkeypatch.setattr("db.migrations.MIGRATIONS", fake_migrations)

    _run_migrations(conn)  # не должно падать


def test_run_migrations_raises_on_unknown_table(monkeypatch):
    """ALTER на несуществующую таблицу — настоящий error → re-raise."""
    conn = _bootstrap_db()
    fake_migrations = [
        "ALTER TABLE nonexistent_table ADD COLUMN x TEXT",
    ]
    monkeypatch.setattr("db.migrations.MIGRATIONS", fake_migrations)

    with pytest.raises(sqlite3.OperationalError):
        _run_migrations(conn)


def test_run_migrations_raises_on_syntax_error(monkeypatch):
    """SQL syntax error — настоящий error → re-raise (не глотать)."""
    conn = _bootstrap_db()
    fake_migrations = [
        "ALTER TABLE foo ADD COLUMN  THIS-IS-INVALID-IDENT",
    ]
    monkeypatch.setattr("db.migrations.MIGRATIONS", fake_migrations)

    with pytest.raises(sqlite3.OperationalError):
        _run_migrations(conn)


def test_partial_failure_stops_iteration(monkeypatch):
    """После raise последующие миграции не выполняются (fail-fast)."""
    conn = _bootstrap_db()
    fake_migrations = [
        "ALTER TABLE nonexistent_table ADD COLUMN x TEXT",  # упадёт
        # Эта мигграция могла бы пройти, но мы до неё не дойдём.
        "ALTER TABLE foo ADD COLUMN never_added TEXT",
    ]
    monkeypatch.setattr("db.migrations.MIGRATIONS", fake_migrations)

    with pytest.raises(sqlite3.OperationalError):
        _run_migrations(conn)

    # Проверим что вторая миграция действительно не применилась.
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(foo)").fetchall()]
    assert "never_added" not in cols
