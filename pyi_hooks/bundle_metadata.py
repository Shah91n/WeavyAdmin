"""
PyInstaller runtime hook — resolves package metadata inside a macOS .app bundle.

PyInstaller places .dist-info folders in Contents/Resources/, but
importlib.metadata only searches Contents/Frameworks/. This hook scans
both locations at startup and patches importlib.metadata.version to fall
back to reading the METADATA file directly when a package is not found.
"""

import importlib.metadata
import os
import sys

if getattr(sys, "frozen", False):
    _lookup: dict[str, str] = {}

    _candidates: list[str] = []
    if hasattr(sys, "_MEIPASS"):
        _candidates.append(sys._MEIPASS)
    if sys.platform == "darwin":
        _resources = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "Resources")
        if _resources not in _candidates:
            _candidates.append(_resources)

    for _cand in _candidates:
        if not os.path.isdir(_cand):
            continue
        for _entry in os.scandir(_cand):
            if _entry.name.endswith(".dist-info") and _entry.is_dir():
                _stem = _entry.name[: -len(".dist-info")]
                _sep = _stem.rfind("-")
                if _sep != -1:
                    _pkg = _stem[:_sep].lower()
                    _lookup[_pkg.replace("-", "_")] = _entry.path
                    _lookup[_pkg.replace("_", "-")] = _entry.path

    if _lookup:
        _orig_version = importlib.metadata.version

        def _version(package_name: str) -> str:
            try:
                return _orig_version(package_name)
            except importlib.metadata.PackageNotFoundError:
                for _k in (
                    package_name.lower().replace("-", "_"),
                    package_name.lower().replace("_", "-"),
                ):
                    _dist_path = _lookup.get(_k)
                    if _dist_path:
                        for _fname in ("METADATA", "PKG-INFO"):
                            _meta = os.path.join(_dist_path, _fname)
                            if os.path.isfile(_meta):
                                with open(_meta, encoding="utf-8", errors="replace") as _f:
                                    for _line in _f:
                                        if _line.startswith("Version:"):
                                            return _line.split(":", 1)[1].strip()
                                        if not _line.strip():
                                            break
                raise

        importlib.metadata.version = _version
