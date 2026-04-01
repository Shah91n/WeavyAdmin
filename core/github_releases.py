"""
core/github_releases.py
=======================
Pure Python helper to fetch the latest GitHub release for a repository.
Zero Qt imports — safe to call from any QThread worker.
"""

import json
import urllib.error
import urllib.request


def fetch_latest_release(owner: str, repo: str) -> dict:
    """Return the GitHub API payload for the latest release.

    Raises
    ------
    urllib.error.HTTPError
        If the release endpoint returns a non-2xx status (e.g. 404 when no
        releases exist yet).
    urllib.error.URLError
        On network failure or DNS timeout.
    ValueError
        If the response body is not valid JSON.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "WeavyAdmin",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NoReleasesError("No releases have been published yet.") from exc
        raise


class NoReleasesError(Exception):
    """Raised when the repository has no published releases."""
