"""
Background QThread worker for batch pprof capture across all Weaviate pods.

Pods are processed sequentially (one port-forward at a time) to avoid port
conflicts on 6060.

Capture order per pod:
  1. Instant profiles (heap, allocs, mutex, goroutine) — sequential.
  2. Goroutine text dump (``?debug=2``).
  3. CPU + fgprof — launched concurrently, waited on together.
  4. SVG flame-graphs for all captured ``.pb.gz`` files.
"""

import logging
import os
import time

from PyQt6.QtCore import QThread, pyqtSignal

from core.infra.profiling.profiling_bridge import ProfilingBridge
from features.infra.pods.worker import fetch_pods

logger = logging.getLogger(__name__)

_DEFAULT_PROFILES = ["heap", "allocs", "mutex", "goroutine", "cpu", "fgprof"]


class ClusterProfilingWorker(QThread):
    """
    Batch pprof capture across all Weaviate pods in the namespace.

    Signals
    -------
    log_line(str)
        Rich log lines mirroring the bash script output.
    pod_started(str)
        Emitted when processing begins for a pod.
    pod_progress(str, str)
        ``(pod_name, current_step)``
    pod_complete(str, bool)
        ``(pod_name, success)``
    overall_progress(int, int)
        ``(pods_done, pods_total)`` after each pod completes.
    all_complete(str)
        Emitted with the final save directory path.
    pod_error(str, str)
        ``(pod_name, error_message)`` – worker continues after per-pod errors.
    fatal_error(str)
        Worker cannot start at all.
    """

    log_line = pyqtSignal(str)
    pod_started = pyqtSignal(str)
    pod_progress = pyqtSignal(str, str)
    pod_complete = pyqtSignal(str, bool)
    overall_progress = pyqtSignal(int, int)
    all_complete = pyqtSignal(str)
    pod_error = pyqtSignal(str, str)
    fatal_error = pyqtSignal(str)

    def __init__(
        self,
        namespace: str,
        duration: int,
        base_save_dir: str,
        profiles: list | None = None,
        cluster_id: str = "",
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.namespace = namespace
        self.duration = duration
        self.base_save_dir = base_save_dir
        self.profiles = profiles or _DEFAULT_PROFILES
        self.cluster_id = cluster_id or namespace
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._log(f"▶ Connecting to cluster: {self.cluster_id}")

            pods_raw = fetch_pods(self.namespace)
            pod_names = [
                p["metadata"]["name"]
                for p in pods_raw
                if p.get("metadata", {}).get("name", "").startswith("weaviate-")
            ]

            if not pod_names:
                self.fatal_error.emit(f"No weaviate-* pods found in namespace '{self.namespace}'.")
                return

            self._log(f"▶ Found {len(pod_names)} pod(s): {', '.join(pod_names)}")

            timestamp = int(time.time())
            folder_name = f"weaviate_profiles_{self.cluster_id}_{timestamp}"
            base_dir = os.path.join(self.base_save_dir, folder_name)
            os.makedirs(base_dir, exist_ok=True)
            self._log(f"▶ Created output directory: {base_dir}")

            total = len(pod_names)

            for idx, pod_name in enumerate(pod_names):
                if self._cancelled:
                    self._log("⛔ Capture cancelled by user.")
                    break

                self._log("=" * 50)
                self._log(f"▶ Processing pod: {pod_name}  ({idx + 1}/{total})")
                self._log("=" * 50)

                pod_dir = os.path.join(base_dir, pod_name)
                os.makedirs(pod_dir, exist_ok=True)
                self.pod_started.emit(pod_name)

                pod_ok = self._capture_pod(pod_name, pod_dir)
                self.pod_complete.emit(pod_name, pod_ok)
                self.overall_progress.emit(idx + 1, total)

                if pod_ok:
                    self._log(f"✅ {pod_name} complete → {pod_dir}")
                else:
                    self._log(f"⚠️  {pod_name} finished with errors (files may be partial)")

            self._log("=" * 50)
            self._log(f"✅ All done. Data saved to: {base_dir}")
            self.all_complete.emit(base_dir)

        except Exception as exc:
            logger.exception("ClusterProfilingWorker fatal error")
            self.fatal_error.emit(str(exc))

    # ------------------------------------------------------------------
    # Per-pod capture
    # ------------------------------------------------------------------

    def _capture_pod(self, pod_name: str, pod_dir: str) -> bool:
        pf_proc = None
        svg_warning_shown = False
        captured_pb: list[tuple[str, str]] = []  # [(profile_name, pb_path)]

        try:
            self._log(f"  → Starting port-forward for {pod_name}…")
            self.pod_progress.emit(pod_name, "Port-forwarding…")
            pf_proc = ProfilingBridge.port_forward(pod_name, self.namespace)
            self._log("  → Port-forward ready on localhost:6060")

            # ── Step 1: instant profiles (sequential) ──────────────────────
            instant = [p for p in self.profiles if p not in ("cpu", "fgprof")]
            self._log("  → 1. Downloading instant profiles (heap, allocs, mutex, goroutine)…")
            for profile_name in instant:
                if self._cancelled:
                    break
                pb_path = os.path.join(pod_dir, f"{profile_name}.pb.gz")
                self._log(f"    - {profile_name}…")
                self.pod_progress.emit(pod_name, f"Capturing {profile_name}…")
                ok = ProfilingBridge.capture_profile(profile_name, self.duration, pb_path)
                if ok:
                    size_kb = os.path.getsize(pb_path) // 1024
                    self._log(f"      ✓ {profile_name}.pb.gz  ({size_kb} KB)")
                    captured_pb.append((profile_name, pb_path))
                else:
                    self._log(f"      ✗ {profile_name}.pb.gz  failed")

            # ── Step 2: goroutine text dump ─────────────────────────────────
            if not self._cancelled:
                dump_path = os.path.join(pod_dir, "goroutine_dump.txt")
                self._log("  → 2. Fetching goroutine text dump…")
                self.pod_progress.emit(pod_name, "Goroutine dump…")
                ok = ProfilingBridge.capture_goroutine_text_dump(dump_path)
                if ok:
                    size_kb = os.path.getsize(dump_path) // 1024
                    self._log(f"    ✓ goroutine_dump.txt  ({size_kb} KB)")
                else:
                    self._log("    ✗ goroutine_dump.txt  failed")

            # ── Step 3: cpu + fgprof concurrently ──────────────────────────
            timed = [p for p in self.profiles if p in ("cpu", "fgprof")]
            if timed and not self._cancelled:
                self._log(
                    f"  → 3. Downloading CPU and fgprof concurrently (duration: {self.duration}s)…"
                )
                self.pod_progress.emit(pod_name, f"cpu + fgprof ({self.duration}s)…")
                concurrent_results = ProfilingBridge.capture_timed_profiles_concurrent(
                    self.duration, pod_dir
                )
                for name, (ok, pb_path) in concurrent_results.items():
                    if name not in timed:
                        continue
                    if ok:
                        size_kb = os.path.getsize(pb_path) // 1024
                        self._log(f"      ✓ {name}.pb.gz  ({size_kb} KB)")
                        captured_pb.append((name, pb_path))
                    else:
                        self._log(f"      ✗ {name}.pb.gz  failed")

            # ── Step 4: SVG flame-graphs ────────────────────────────────────
            if captured_pb and not self._cancelled:
                self._log("  → 4. Generating SVG graphs…")
                for profile_name, pb_path in captured_pb:
                    svg_path = os.path.join(pod_dir, f"{profile_name}.svg")
                    self.pod_progress.emit(pod_name, f"SVG {profile_name}…")
                    svg_ok, svg_warning = ProfilingBridge.generate_svg(pb_path, svg_path)
                    if svg_ok:
                        size_kb = os.path.getsize(svg_path) // 1024
                        self._log(f"      ✓ {profile_name}.svg  ({size_kb} KB)")
                    elif svg_warning and not svg_warning_shown:
                        self._log(f"      {svg_warning}")
                        svg_warning_shown = True

            return True

        except Exception as exc:
            logger.exception("Error capturing profiles for pod %s", pod_name)
            self._log(f"  ✗ Error: {exc}")
            self.pod_error.emit(pod_name, str(exc))
            return False

        finally:
            if pf_proc is not None:
                self._log(f"  → Stopping port-forward for {pod_name}")
                self.pod_progress.emit(pod_name, "Stopping port-forward…")
                ProfilingBridge.stop_port_forward(pf_proc)

    def _log(self, msg: str) -> None:
        self.log_line.emit(msg)
