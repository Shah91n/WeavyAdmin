"""
Worker thread for CSV ingestion with progress tracking and error reporting.
Supports both standard and Multi-Tenant collections with non-blocking architecture.
"""

import csv
from collections.abc import Callable, Iterable
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.collections import (
    add_tenant_to_collection,
    batch_ingest_mt,
    batch_ingest_standard,
    build_header_map,
    check_collection_mt_status,
    check_vectorizer_requirements,
    create_collection_mt,
    create_collection_standard,
    detect_vector_column,
    validate_csv_file,
)


class IngestWorker(QThread):
    """
    Background worker for CSV data ingestion.

    Signals:
        progress: Emits (current: int, total: int, message: str)
        finished: Emits (success_count: int, failed_count: int, total_count: int)
        error: Emits (error_message: str)
        log_message: Emits (line: str) — streaming log output for the UI log box
    """

    # Signals
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal(int, int, int)  # success_count, failed_count, total_count
    error = pyqtSignal(str)  # error_message
    log_message = pyqtSignal(str)  # streaming log line

    def __init__(
        self,
        file_path: str,
        collection_name: str,
        vectorizer: str,
        is_multi_tenant: bool = False,
        tenant_name: str | None = None,
        vector_column_override: str | None = None,
    ):
        """
        Initialize the ingest worker.

        Args:
            file_path: Path to CSV file
            collection_name: Collection name
            vectorizer: Selected vectorizer
            is_multi_tenant: Whether to use multi-tenant mode
            tenant_name: Tenant name (required if is_multi_tenant=True)
            vector_column_override: Optional override for vector column detection
        """
        super().__init__()
        self.file_path = file_path
        self.collection_name = collection_name
        self.vectorizer = vectorizer
        self.is_multi_tenant = is_multi_tenant
        self.tenant_name = tenant_name
        self.vector_column_override = vector_column_override
        self._is_running = True

    def stop(self):
        """Request the worker to stop."""
        self._is_running = False

    def run(self) -> None:
        """Execute the ingestion pipeline."""
        try:
            # Step 1: Validate CSV file
            self.progress.emit(0, 100, "Validating CSV file...")
            self.log_message.emit("Validating CSV file...")
            valid, message, headers = validate_csv_file(self.file_path)

            if not valid:
                self.error.emit(message)
                return

            if not self._is_running:
                return

            # Step 2: Check vectorizer requirements
            self.progress.emit(10, 100, "Checking vectorizer requirements...")
            self.log_message.emit(f"Checking vectorizer requirements ({self.vectorizer})...")
            has_keys, key_message = check_vectorizer_requirements(self.vectorizer)

            if not has_keys:
                self.error.emit(key_message)
                return

            if not self._is_running:
                return

            # Step 3: Determine if BYOV and detect vector column
            is_byov = self.vectorizer == "BYOV"
            vector_column = None

            if is_byov:
                self.progress.emit(15, 100, "Detecting vector column...")
                vector_column = self.vector_column_override or detect_vector_column(headers)
                if not vector_column:
                    self.error.emit(
                        "BYOV selected but no vector column detected. "
                        "Please ensure your CSV has a column named 'vector', 'embedding', or similar."
                    )
                    return
                self.log_message.emit(f"Using vector column: {vector_column}")

            if not self._is_running:
                return

            # Step 4: Prepare streaming ingestion
            self.progress.emit(20, 100, "Preparing CSV stream...")
            header_map = build_header_map(headers)
            total_rows = self._count_csv_rows()

            if total_rows == 0:
                self.error.emit("No data found in CSV file")
                return

            self.progress.emit(30, 100, f"Found {total_rows} rows in CSV")
            self.log_message.emit(f"Found {total_rows} rows in CSV.")

            if not self._is_running:
                return

            # Step 5: Handle collection/tenant setup
            if self.is_multi_tenant:
                success = self._setup_mt_collection()
            else:
                success = self._setup_standard_collection()

            if not success:
                return

            if not self._is_running:
                return

            # Step 6: Perform batch ingestion
            self.progress.emit(50, 100, "Starting batch ingestion...")
            self.log_message.emit("Starting batch ingestion...")

            rows = self._iter_csv_rows()
            if self.is_multi_tenant:
                success_count, failed_list = self._ingest_mt(
                    rows, header_map, total_rows, is_byov, vector_column
                )
            else:
                success_count, failed_list = self._ingest_standard(
                    rows, header_map, total_rows, is_byov, vector_column
                )

            if not self._is_running:
                return

            # Step 7: Report results
            failed_count = len(failed_list)
            self.progress.emit(100, 100, "Ingestion completed")
            self.finished.emit(success_count, failed_count, total_rows)

        except Exception as e:
            self.log_message.emit(f"Unexpected error: {e}")
            self.error.emit(f"Unexpected error: {str(e)}")

    def _count_csv_rows(self) -> int:
        """Count rows in CSV (excluding header) without loading into memory."""
        count = 0
        with open(self.file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for _ in reader:
                count += 1
        return count

    def _iter_csv_rows(self) -> Iterable[dict[str, Any]]:
        """Stream CSV rows one by one."""
        with open(self.file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not self._is_running:
                    break
                yield row

    def _setup_standard_collection(self) -> bool:
        """Setup standard (non-MT) collection."""
        self.progress.emit(35, 100, "Setting up collection...")

        # Check if collection exists
        exists, is_mt = check_collection_mt_status(self.collection_name)

        if exists:
            if is_mt:
                self.error.emit(
                    f"Collection '{self.collection_name}' exists but is MT-enabled. "
                    "Please use a different name or enable Multi-Tenant mode."
                )
                return False
            # Collection exists and is standard - use it
            self.progress.emit(40, 100, f"Using existing collection '{self.collection_name}'")
            self.log_message.emit(f"Using existing collection '{self.collection_name}'.")
        else:
            # Create new standard collection
            self.progress.emit(40, 100, f"Creating collection '{self.collection_name}'...")
            self.log_message.emit(f"Creating collection '{self.collection_name}'...")
            success, message = create_collection_standard(self.collection_name, self.vectorizer)

            if not success:
                self.error.emit(message)
                return False

            self.progress.emit(45, 100, message)
            self.log_message.emit(message)

        return True

    def _setup_mt_collection(self) -> bool:
        """Setup Multi-Tenant collection and tenant."""
        self.progress.emit(35, 100, "Setting up MT collection...")

        if not self.tenant_name:
            self.error.emit("Tenant name is required for Multi-Tenant mode")
            return False

        # Check if collection exists
        exists, is_mt = check_collection_mt_status(self.collection_name)

        if exists:
            if not is_mt:
                self.error.emit(
                    f"Collection '{self.collection_name}' exists but is NOT MT-enabled. "
                    "Cannot ingest into non-MT collection in MT mode."
                )
                return False

            # Collection exists and is MT - add tenant
            self.progress.emit(40, 100, f"Adding tenant '{self.tenant_name}' to collection...")
            self.log_message.emit(
                f"Adding tenant '{self.tenant_name}' to collection '{self.collection_name}'..."
            )
            success, message = add_tenant_to_collection(self.collection_name, self.tenant_name)

            if not success:
                self.error.emit(message)
                return False

            self.progress.emit(45, 100, f"Using tenant '{self.tenant_name}'")
            self.log_message.emit(message)
        else:
            # Create new MT collection with first tenant
            self.progress.emit(
                40,
                100,
                f"Creating MT collection '{self.collection_name}' with tenant '{self.tenant_name}'...",
            )
            self.log_message.emit(
                f"Creating MT collection '{self.collection_name}' with tenant '{self.tenant_name}'..."
            )
            success, message = create_collection_mt(
                self.collection_name, self.vectorizer, self.tenant_name
            )

            if not success:
                self.error.emit(message)
                return False

            self.progress.emit(45, 100, message)
            self.log_message.emit(message)

        return True

    def _make_progress_callback(self) -> Callable[[int, int], None]:
        def progress_callback(current: int, total: int) -> None:
            if not self._is_running:
                return
            if total > 0:
                percentage = 50 + int((current / total) * 45)
                self.progress.emit(percentage, 100, f"Ingesting: {current}/{total} objects")
            else:
                self.progress.emit(50, 100, f"Ingesting: {current} objects")

        return progress_callback

    def _log_callback(self, line: str) -> None:
        if self._is_running:
            self.log_message.emit(line)

    def _ingest_standard(
        self,
        rows: Iterable[dict[str, Any]],
        header_map: dict[str, str],
        total_count: int,
        is_byov: bool,
        vector_column: str | None,
    ) -> tuple:
        """Perform standard collection ingestion."""
        return batch_ingest_standard(
            collection_name=self.collection_name,
            rows=rows,
            header_map=header_map,
            is_byov=is_byov,
            vector_column=vector_column,
            total_count=total_count,
            progress_callback=self._make_progress_callback(),
            log_callback=self._log_callback,
        )

    def _ingest_mt(
        self,
        rows: Iterable[dict[str, Any]],
        header_map: dict[str, str],
        total_count: int,
        is_byov: bool,
        vector_column: str | None,
    ) -> tuple:
        """Perform Multi-Tenant collection ingestion."""
        return batch_ingest_mt(
            collection_name=self.collection_name,
            tenant_name=self.tenant_name,
            rows=rows,
            header_map=header_map,
            is_byov=is_byov,
            vector_column=vector_column,
            total_count=total_count,
            progress_callback=self._make_progress_callback(),
            log_callback=self._log_callback,
        )
