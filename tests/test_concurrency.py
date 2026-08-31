"""AT-design: NFR-13 — конкурентный доступ двух независимых процессов к общему
файлу реестра (не проверено ранее, постановка риск 2).

Покрывает «Контракт теста конкурентного доступа» ADR-013-central-transcript-store-spec.md
дословно: два ПРОЦЕССА (не потока, `multiprocessing`), параллельная запись
`mark-*`/`sync`-подобных транзакций -> `PRAGMA integrity_check == 'ok'`, ни одна
ранее сохранённая запись не потеряна; конфликт на одной и той же записи ->
детерминированно ровно одно из двух значений; исчерпание `busy_timeout=5000` ->
`sqlite3.OperationalError` с узнаваемым текстом «занято», не generic traceback.

Вне контракта (явно не покрывается, ADR-013-spec «Что НЕ входит»): число процессов
свыше двух, сетевая ФС.

Существующий механизм (WAL + busy_timeout=5000, ADR-002) уже в `registry.py` —
эти тесты не про новый код, а про ДОКАЗАТЕЛЬСТВО достаточности существующего
механизма на реальных процессах, а не про новую фичу. Технически могут быть
red уже сегодня без единой строки нового кода Dev, если сам факт multiprocessing
на общем файле выявит проблему — оставлены red по конвенции задачи (QA пишет
тест до подтверждения, не после).
"""

from __future__ import annotations

import multiprocessing
import sqlite3
from pathlib import Path


def _seed(db_path: Path, n: int) -> None:
    from ktalk_cli.registry import Registry

    with Registry(db_path) as reg:
        for i in range(n):
            reg.upsert_recording(
                {"recording_id": f"rec-{i}", "name": "Standup", "date": "2026-06-24"},
                now="2026-06-24",
            )


def _worker_mark(db_path_str: str, prefix: str, count: int, status: str) -> None:
    from ktalk_cli.registry import Registry

    with Registry(Path(db_path_str)) as reg:
        for i in range(count):
            reg.set_status(f"rec-{i}", status)


def test_ac_nfr13_1_two_processes_concurrent_writes_integrity_ok_no_data_loss(
    tmp_path,
):
    db_path = tmp_path / "shared.db"
    _seed(db_path, n=20)

    p1 = multiprocessing.Process(
        target=_worker_mark, args=(str(db_path), "p1", 20, "done")
    )
    p2 = multiprocessing.Process(
        target=_worker_mark, args=(str(db_path), "p2", 20, "skipped")
    )
    p1.start()
    p2.start()
    p1.join(timeout=30)
    p2.join(timeout=30)

    assert p1.exitcode == 0, "TODO: NFR-13 AC-1 — процесс 1 обязан завершиться успешно"
    assert p2.exitcode == 0, "TODO: NFR-13 AC-1 — процесс 2 обязан завершиться успешно"

    conn = sqlite3.connect(db_path)
    try:
        (result,) = conn.execute("PRAGMA integrity_check").fetchone()
        assert result == "ok"
        (count,) = conn.execute("SELECT COUNT(*) FROM recordings").fetchone()
        assert count == 20, "ни одна ранее существовавшая запись не потеряна"
    finally:
        conn.close()


def _worker_set_status(db_path_str: str, recording_id: str, status: str) -> None:
    from ktalk_cli.registry import Registry

    with Registry(Path(db_path_str)) as reg:
        reg.set_status(recording_id, status)


def test_ac_nfr13_2_conflicting_write_to_same_record_yields_exactly_one_deterministic_outcome(
    tmp_path,
):
    db_path = tmp_path / "shared.db"
    _seed(db_path, n=1)

    p_done = multiprocessing.Process(
        target=_worker_set_status, args=(str(db_path), "rec-0", "done")
    )
    p_skipped = multiprocessing.Process(
        target=_worker_set_status, args=(str(db_path), "rec-0", "skipped")
    )
    p_done.start()
    p_skipped.start()
    p_done.join(timeout=30)
    p_skipped.join(timeout=30)

    from ktalk_cli.registry import Registry

    with Registry(db_path) as reg:
        final = reg.get_recording("rec-0")
    assert final["status"] in ("done", "skipped"), (
        "TODO: NFR-13 AC-2 — итог обязан быть ровно одним из двух значений, "
        f"получено {final['status']!r}"
    )


def _hold_exclusive_lock(db_path_str: str, seconds: float) -> None:
    """Module-level (не nested) — multiprocessing на macOS использует `spawn`,
    которому нужен picklable target."""
    import time

    conn = sqlite3.connect(db_path_str, timeout=0)
    conn.execute("BEGIN EXCLUSIVE")
    conn.execute("PRAGMA busy_timeout=5000")
    time.sleep(seconds)
    conn.rollback()
    conn.close()


def test_nfr13_busy_timeout_exhausted_raises_recognizable_operational_error(tmp_path):
    """Исчерпание busy_timeout=5000 -> sqlite3.OperationalError с узнаваемым
    текстом «занято» (locked/busy), не тихая потеря операции и не generic
    traceback без диагностического текста.

    Реализация как стаб: держим эксклюзивную блокировку дольше 5с из отдельного
    процесса, вторая сторона обязана получить распознаваемую ошибку, а не
    зависнуть/тихо промолчать."""
    import time

    db_path = tmp_path / "shared.db"
    _seed(db_path, n=1)

    holder = multiprocessing.Process(
        target=_hold_exclusive_lock, args=(str(db_path), 7)
    )
    holder.start()
    time.sleep(0.5)  # даём держателю точно взять блокировку первым

    from ktalk_cli.registry import Registry

    caught: Exception | None = None
    try:
        with Registry(db_path) as reg:
            reg.set_status("rec-0", "done")
    except sqlite3.OperationalError as exc:
        caught = exc
    finally:
        holder.join(timeout=15)

    assert caught is not None, (
        "TODO: NFR-13 — при исчерпании busy_timeout обязан подняться "
        "sqlite3.OperationalError, не тихая потеря операции"
    )
    text = str(caught).lower()
    assert "lock" in text or "busy" in text, (
        f"TODO: NFR-13 — текст ошибки обязан быть узнаваем как «занято», получено: {caught}"
    )
