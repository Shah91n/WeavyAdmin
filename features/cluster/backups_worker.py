"""Workers for backup operations (list, create, restore, cancel)."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class BackupsWorker(QThread):
    """Background worker to fetch the cluster backup list."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, get_backups_func):
        super().__init__()
        self.get_backups_func = get_backups_func

    def run(self) -> None:
        try:
            data = self.get_backups_func()
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(f"Failed to fetch backups: {str(e)}")


class CreateBackupWorker(QThread):
    """Background worker to start a backup creation."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, backup_id: str, include_collections: list | None = None):
        super().__init__()
        self.backup_id = backup_id
        self.include_collections = include_collections

    def run(self) -> None:
        from core.weaviate.cluster import create_backup

        try:
            result = create_backup(self.backup_id, self.include_collections)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class RestoreBackupWorker(QThread):
    """Background worker to start a backup restore."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, backup_id: str, include_collections: list | None = None):
        super().__init__()
        self.backup_id = backup_id
        self.include_collections = include_collections

    def run(self) -> None:
        from core.weaviate.cluster import restore_backup

        try:
            result = restore_backup(self.backup_id, self.include_collections)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class CancelBackupWorker(QThread):
    """Background worker to cancel a running backup or restore."""

    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, backup_id: str, operation: str = "create"):
        super().__init__()
        self.backup_id = backup_id
        self.operation = operation

    def run(self) -> None:
        from core.weaviate.cluster import cancel_backup

        try:
            result = cancel_backup(self.backup_id, self.operation)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
