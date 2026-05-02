"""
tests/test_workouts_concurrency.py — Защита от двойной записи в log_workout / log_metrics.

Singleton sqlite3-соединение с check_same_thread=False допускает Python-уровневую
гонку SELECT-then-INSERT между потоками (handler-asyncio + APScheduler-thread).
В db/queries/workouts.py добавлен threading.Lock — этот тест-стресс верифицирует,
что параллельные вызовы upsert не создают дубликатов.
"""
import threading
import pytest

from db.queries.workouts import log_workout, log_metrics
from tests.conftest import insert_user


_THREADS = 16
_ITERATIONS = 5


class TestLogWorkoutConcurrency:

    def test_parallel_calls_same_key_no_duplicates(self, patched_db):
        user_id = insert_user(patched_db, telegram_id=200001)
        date = "2026-05-02"
        workout_type = "strength"
        barrier = threading.Barrier(_THREADS)
        errors: list[Exception] = []

        def worker(intensity: int) -> None:
            try:
                barrier.wait()
                for _ in range(_ITERATIONS):
                    log_workout(
                        user_id=user_id,
                        date=date,
                        mode="MAX",
                        workout_type=workout_type,
                        intensity=intensity,
                        completed=True,
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=((i % 10) + 1,)) for i in range(_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Worker exceptions: {errors}"
        rows = patched_db.execute(
            "SELECT id FROM workouts WHERE user_id = ? AND date = ? AND type = ?",
            (user_id, date, workout_type),
        ).fetchall()
        assert len(rows) == 1, f"expected 1 row, got {len(rows)}"

    def test_parallel_calls_distinct_types_create_distinct_rows(self, patched_db):
        user_id = insert_user(patched_db, telegram_id=200002)
        date = "2026-05-02"
        types = ["strength", "cardio", "stretch"]
        barrier = threading.Barrier(len(types) * 4)
        errors: list[Exception] = []

        def worker(wtype: str) -> None:
            try:
                barrier.wait()
                log_workout(user_id=user_id, date=date, mode="MAX",
                            workout_type=wtype, completed=True)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(t,))
            for t in types for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        rows = patched_db.execute(
            "SELECT type, COUNT(*) c FROM workouts WHERE user_id = ? AND date = ? GROUP BY type",
            (user_id, date),
        ).fetchall()
        assert {r["type"] for r in rows} == set(types)
        for r in rows:
            assert r["c"] == 1, f"type {r['type']} has {r['c']} rows, expected 1"


class TestLogMetricsConcurrency:

    def test_parallel_calls_same_date_no_duplicates(self, patched_db):
        user_id = insert_user(patched_db, telegram_id=200003)
        date = "2026-05-02"
        barrier = threading.Barrier(_THREADS)
        errors: list[Exception] = []

        def worker(weight: float) -> None:
            try:
                barrier.wait()
                for _ in range(_ITERATIONS):
                    log_metrics(user_id=user_id, date=date, weight_kg=weight)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(70.0 + i,)) for i in range(_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        rows = patched_db.execute(
            "SELECT id FROM metrics WHERE user_id = ? AND date = ?",
            (user_id, date),
        ).fetchall()
        assert len(rows) == 1
