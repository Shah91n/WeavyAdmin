"""
Background QThread workers for single-pod pprof profiling.

ProfilingGoroutineWorker  – quick goroutine health-check (dump + parse).
ProfilingCaptureWorker    – full profile capture (.pb.gz + SVG + text dump).
ProfilingAnalysisWorker   – Claude AI analysis of a goroutine dump.

Capture order:
  1. Instant profiles (heap, allocs, mutex, goroutine) — sequential.
  2. Goroutine text dump.
  3. CPU + fgprof — launched concurrently, both waited on.
  4. SVG flame-graphs for all captured .pb.gz files.

SVG generation uses ``go tool pprof -svg``.  If ``go`` is not found, a
warning is emitted via the ``progress`` signal so the user sees it clearly
rather than it being silently swallowed.
"""

import logging
import os

from PyQt6.QtCore import QThread, pyqtSignal

from core.infra.profiling.profile_parser import parse_goroutine_dump
from core.infra.profiling.profiling_bridge import ProfilingBridge

logger = logging.getLogger(__name__)


class ProfilingGoroutineWorker(QThread):
    """
    Captures a goroutine text dump for a single pod and parses it.

    Steps
    -----
    1. Start port-forward.
    2. Fetch ``goroutine.pb.gz`` (for external pprof use).
    3. Fetch ``goroutine_dump.txt`` (``?debug=2`` text dump).
    4. Parse dump and emit results.

    Signals
    -------
    progress(str)
        Human-readable status / warning messages.
    goroutine_ready(dict, str, str)
        (parsed_metrics, dump_file_path, "").
        Third argument is kept for UI compatibility but is always ``""``.
    error(str)
        Emitted on failure.
    """

    progress = pyqtSignal(str)
    goroutine_ready = pyqtSignal(dict, str, str)
    error = pyqtSignal(str)

    def __init__(
        self,
        pod_name: str,
        namespace: str,
        save_dir: str,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.pod_name = pod_name
        self.namespace = namespace
        self.save_dir = save_dir

    def run(self) -> None:
        pf_proc = None
        try:
            os.makedirs(self.save_dir, exist_ok=True)

            self.progress.emit(f"Starting port-forward for {self.pod_name}…")
            pf_proc = ProfilingBridge.port_forward(self.pod_name, self.namespace)

            # .pb.gz – saved for external pprof analysis
            pb_path = os.path.join(self.save_dir, "goroutine.pb.gz")
            self.progress.emit("Capturing goroutine.pb.gz…")
            ProfilingBridge.capture_profile("goroutine", 0, pb_path)

            # Text dump – main input for in-app analysis
            dump_path = os.path.join(self.save_dir, "goroutine_dump.txt")
            self.progress.emit("Fetching goroutine text dump…")
            ok = ProfilingBridge.capture_goroutine_text_dump(dump_path)
            if not ok:
                self.error.emit(
                    "Failed to capture goroutine dump. Is the pod reachable on port 6060?"
                )
                return

            # Parse
            self.progress.emit("Parsing dump…")
            with open(dump_path, encoding="utf-8", errors="replace") as f:
                dump_text = f.read()

            metrics = parse_goroutine_dump(dump_text)
            self.goroutine_ready.emit(metrics, dump_path, "")

        except Exception as exc:
            logger.exception("ProfilingGoroutineWorker error")
            self.error.emit(str(exc))
        finally:
            if pf_proc is not None:
                ProfilingBridge.stop_port_forward(pf_proc)


_INSTANT_PROFILES = {"heap", "allocs", "mutex", "goroutine"}
_TIMED_PROFILES = {"cpu", "fgprof"}


class ProfilingCaptureWorker(QThread):
    """
    Captures the full set of pprof profiles for a single pod.

    Capture order (mirrors the reference bash script):
      1. Instant profiles (heap, allocs, mutex, goroutine) — sequential.
      2. Goroutine text dump (``?debug=2``).
      3. CPU + fgprof — launched concurrently, waited on together.
      4. SVG flame-graphs for all captured ``.pb.gz`` files.

    If ``go`` is not found, an SVG warning is emitted once (not per profile).

    Signals
    -------
    progress(str)
        Human-readable status / warning messages.
    profile_started(str)
        Emitted when a profile capture begins: ``profile_name``.
    profile_complete(str, str, bool)
        Emitted when a profile finishes: ``(profile_name, file_path, success)``.
    all_complete(dict)
        Emitted on success: ``{key: file_path}`` for all saved files.
        Keys follow the pattern ``"cpu"``, ``"cpu_svg"``, ``"goroutine_dump"``, etc.
    error(str)
        Emitted on fatal failure (e.g. port-forward could not start).
    """

    progress = pyqtSignal(str)
    profile_started = pyqtSignal(str)
    profile_complete = pyqtSignal(str, str, bool)
    all_complete = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        pod_name: str,
        namespace: str,
        duration: int,
        save_dir: str,
        profiles: list,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.pod_name = pod_name
        self.namespace = namespace
        self.duration = duration
        self.save_dir = save_dir
        self.profiles = profiles

    def run(self) -> None:
        pf_proc = None
        results: dict[str, str] = {}
        svg_warning_shown = False

        try:
            os.makedirs(self.save_dir, exist_ok=True)

            self.progress.emit(f"Starting port-forward for {self.pod_name}…")
            pf_proc = ProfilingBridge.port_forward(self.pod_name, self.namespace)

            # ── Step 1: instant profiles (sequential) ──────────────────────
            instant = [p for p in self.profiles if p in _INSTANT_PROFILES]
            self.progress.emit("Capturing instant profiles (heap, allocs, mutex, goroutine)…")
            for profile_name in instant:
                pb_path = os.path.join(self.save_dir, f"{profile_name}.pb.gz")
                self.profile_started.emit(profile_name)
                self.progress.emit(f"Capturing {profile_name}…")
                ok = ProfilingBridge.capture_profile(profile_name, self.duration, pb_path)
                if ok:
                    results[profile_name] = pb_path
                self.profile_complete.emit(profile_name, pb_path if ok else "", ok)

            # ── Step 2: goroutine text dump ─────────────────────────────────
            dump_path = os.path.join(self.save_dir, "goroutine_dump.txt")
            self.progress.emit("Fetching goroutine text dump…")
            if ProfilingBridge.capture_goroutine_text_dump(dump_path):
                results["goroutine_dump"] = dump_path

            # ── Step 3: cpu + fgprof concurrently ──────────────────────────
            timed = [p for p in self.profiles if p in _TIMED_PROFILES]
            if timed:
                self.progress.emit(
                    f"Capturing cpu + fgprof concurrently (duration: {self.duration}s)…"
                )
                for name in timed:
                    self.profile_started.emit(name)
                concurrent_results = ProfilingBridge.capture_timed_profiles_concurrent(
                    self.duration, self.save_dir
                )
                for name, (ok, pb_path) in concurrent_results.items():
                    if name not in timed:
                        continue
                    if ok:
                        results[name] = pb_path
                    self.profile_complete.emit(name, pb_path if ok else "", ok)

            # ── Step 4: SVG flame-graphs ────────────────────────────────────
            all_pb = [
                (k, v)
                for k, v in results.items()
                if not k.endswith("_svg") and k != "goroutine_dump" and v.endswith(".pb.gz")
            ]
            for profile_name, pb_path in all_pb:
                svg_path = os.path.join(self.save_dir, f"{profile_name}.svg")
                self.progress.emit(f"Generating {profile_name}.svg…")
                svg_ok, svg_warning = ProfilingBridge.generate_svg(pb_path, svg_path)
                if svg_ok:
                    results[f"{profile_name}_svg"] = svg_path
                elif svg_warning and not svg_warning_shown:
                    self.progress.emit(svg_warning)
                    svg_warning_shown = True

            self.all_complete.emit(results)

        except Exception as exc:
            logger.exception("ProfilingCaptureWorker error")
            self.error.emit(str(exc))
        finally:
            if pf_proc is not None:
                self.progress.emit("Stopping port-forward…")
                ProfilingBridge.stop_port_forward(pf_proc)


class ProfilingAnalysisWorker(QThread):
    """
    Sends a structured goroutine summary to Claude for AI-powered analysis.

    Uses parsed metrics (not the raw dump) so input size is bounded
    regardless of cluster scale.

    Signals
    -------
    finished(str)
        Emitted with the formatted analysis text on completion (or an error).
    """

    finished = pyqtSignal(str)

    def __init__(
        self,
        api_key: str,
        pod_name: str,
        metrics: dict,
        mode: str = "quick",
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self._api_key = api_key
        self._pod_name = pod_name
        self._metrics = metrics
        self._mode = mode

    def run(self) -> None:
        try:
            from core.infra.profiling.claude_analyzer import analyze_goroutine_dump

            result = analyze_goroutine_dump(
                self._api_key, self._pod_name, self._metrics, self._mode
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("ProfilingAnalysisWorker error")
            self.finished.emit(f"Analysis failed: {exc}")
