"""
backup.py — Резервное копирование SQLite базы.
"""
import logging
import shutil
import datetime
import os
from config import DB_PATH, BACKUP_DIR

logger = logging.getLogger(__name__)


def run_backup() -> str:
    """Копирует DB в backups/trainer_YYYY-MM-DD.db. Возвращает путь."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    dest = os.path.join(BACKUP_DIR, f"trainer_{date_str}.db")

    if not os.path.exists(DB_PATH):
        logger.warning("DB file not found, skipping backup")
        return ""

    shutil.copy2(DB_PATH, dest)
    logger.info(f"Backup saved: {dest}")

    # Удалить бэкапы старше 90 дней
    _cleanup_old_backups(keep_days=90)
    return dest


def _cleanup_old_backups(keep_days: int = 90) -> None:
    cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
    for fname in os.listdir(BACKUP_DIR):
        if not fname.startswith("trainer_") or not fname.endswith(".db"):
            continue
        fpath = os.path.join(BACKUP_DIR, fname)
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
        if mtime < cutoff:
            os.remove(fpath)
            logger.info(f"Old backup removed: {fname}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = run_backup()
    logger.info(f"Backup done: {path}")
