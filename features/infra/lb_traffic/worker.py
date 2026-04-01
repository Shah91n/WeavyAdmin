"""
Background QThread worker that fetches GCP HTTP Load Balancer traffic
off the UI thread and emits it as a list of parsed dicts.
"""

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.infra.gcp.lb_traffic import GCPLBTraffic


class LBTrafficWorker(QThread):
    """
    Fetches GCP Load Balancer traffic entries in a background thread.

    Parameters
    ----------
    project_id:
        GCP project ID (e.g. ``wcs-prod-cust-europe-west3``).
    cluster_id:
        Weaviate cluster ID extracted from the URL
        (e.g. ``cttmbwrjzvpevk7rl5g``).
    limit:
        Maximum number of entries to retrieve (default 5,000).

    Signals
    -------
    traffic_ready(list)
        Emitted with the list of parsed traffic dicts on success.
    progress(str)
        Emitted with informational status messages during fetch.
    error(str)
        Emitted with an error message on failure.
    """

    traffic_ready = pyqtSignal(list)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        project_id: str,
        cluster_id: str,
        limit: int = 5_000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.cluster_id = cluster_id
        self.limit = limit

    def run(self) -> None:
        try:
            self.progress.emit(
                f"Fetching LB traffic for '{self.cluster_id}' in project '{self.project_id}' …"
            )
            fetcher = GCPLBTraffic(self.project_id, self.cluster_id, self.limit)
            entries = fetcher.fetch()
            self.traffic_ready.emit(entries)
        except Exception as exc:
            self.error.emit(str(exc))
