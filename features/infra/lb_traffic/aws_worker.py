"""
Background QThread worker that fetches Istio/Envoy gateway logs for an
AWS Weaviate Cloud cluster off the UI thread and emits them as a list of
parsed dicts.
"""

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.infra.aws.lb_traffic import AWSLBTraffic


class AWSLBTrafficWorker(QThread):
    """
    Fetches AWS gateway (Istio) traffic entries in a background thread.

    Parameters
    ----------
    cluster_id:
        Weaviate cluster ID extracted from the URL
        (e.g. ``kckx8mixq6cnpwbupqfgeq``).
    since:
        How far back to fetch logs.  Accepts the shared time-window values
        (``"1h"``, ``"12h"``, ``"1d"``, ``"3d"``, ``"5d"``, ``"7d"``).
        Default ``"1h"``.

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
        cluster_id: str,
        since: str = "1h",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.cluster_id = cluster_id
        self.since = since

    def run(self) -> None:
        try:
            self.progress.emit(
                f"Discovering gateway pod and fetching traffic "
                f"for cluster '{self.cluster_id}' (last {self.since}) …"
            )
            fetcher = AWSLBTraffic(self.cluster_id, since=self.since)
            entries = fetcher.fetch()
            self.traffic_ready.emit(entries)
        except Exception as exc:
            self.error.emit(str(exc))
