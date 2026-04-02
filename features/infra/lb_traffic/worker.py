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
    freshness:
        How far back to fetch logs, passed directly to ``gcloud --freshness``
        (e.g. ``"1h"``, ``"12h"``, ``"1d"``, ``"7d"``).  Default ``"1h"``.

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
        freshness: str = "1h",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_id = project_id
        self.cluster_id = cluster_id
        self.freshness = freshness

    def run(self) -> None:
        try:
            self.progress.emit(
                f"Fetching LB traffic for '{self.cluster_id}' "
                f"in project '{self.project_id}' (last {self.freshness}) …"
            )
            fetcher = GCPLBTraffic(self.project_id, self.cluster_id, freshness=self.freshness)
            entries = fetcher.fetch()
            self.traffic_ready.emit(entries)
        except Exception as exc:
            self.error.emit(str(exc))
