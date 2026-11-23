"""Collect work-log files from every branch of a repository.

Two backends with the same output:
  * GitHubSource  - GitHub REST API (what the scheduled Action uses)
  * LocalGitSource - a local clone (fast, offline, used for backtests)

Failures are reported, never fatal: one unreadable branch must not stop the
weekly digest for everyone else.
"""
from __future__ import annotations

import base64
import fnmatch
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .models import Entry
from .parser import parse_log

DEFAULT_PATTERNS = ["*work.log*", "*worklog*"]
SKIP_SUFFIXES = (".json", ".jsonl", ".csv", ".pyc", ".py", ".ipynb")
SKIP_BRANCHES = ("HEAD", "claude/*")


@dataclass
class LogFile:
    repo: str
    branch: str
    path: str
    text: str


@dataclass
class IngestResult:
    files: list[LogFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def entries(self, author_map: dict[str, str] | None = None,
                mentor_branches: tuple[str, ...] = (),
                mentor_files: tuple[str, ...] = ()) -> list[Entry]:
        """Parse intern entries.

        The mentor's own log is seeded into every intern branch (as a separate
        file in 2026, as the first entry of the intern's file in 2025). Entries
        that are identical to a mentor entry are dropped so they are not
        attributed to an intern.
        """
        mentor, interns = [], []
        for f in self.files:
            is_mentor = f.branch in mentor_branches or os.path.basename(f.path) in mentor_files
            author = "mentor" if is_mentor else (author_map or {}).get(f.branch, f.branch.split("/")[0])
            (mentor if is_mentor else interns).extend(
                parse_log(f.text, author, f.repo, f.branch, f.path))
        fp = {_fingerprint(e) for e in mentor}
        return [e for e in interns if _fingerprint(e) not in fp]


def _fingerprint(e: Entry) -> tuple:
    return (e.raw_date, tuple(t.text for t in e.done))


def _wanted(path: str, patterns: list[str]) -> bool:
    base = os.path.basename(path).lower()
    return (any(fnmatch.fnmatch(base, p) for p in patterns)
            and not base.endswith(SKIP_SUFFIXES))


def _skip_branch(b: str) -> bool:
    return any(fnmatch.fnmatch(b, p) for p in SKIP_BRANCHES)


class DirSource:
    """A plain folder of log files, one file per intern (used for the demo data).

    The file name without extension is used as the intern name / branch.
    """
    def __init__(self, folder: str, repo_name: str = "demo"):
        self.folder, self.repo = folder, repo_name

    def collect(self) -> IngestResult:
        res = IngestResult()
        for name in sorted(os.listdir(self.folder)):
            path = os.path.join(self.folder, name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    res.files.append(LogFile(self.repo, name.split(".")[0], name, f.read()))
            except (OSError, UnicodeDecodeError) as e:
                res.errors.append(f"{name}: {e}")
        return res


class LocalGitSource:
    def __init__(self, clone_dir: str, repo_name: str | None = None,
                 patterns: list[str] | None = None):
        self.dir = clone_dir
        self.repo = repo_name or os.path.basename(os.path.abspath(clone_dir))
        self.patterns = patterns or DEFAULT_PATTERNS

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", self.dir, *args], check=True,
                              capture_output=True, text=True).stdout

    def collect(self) -> IngestResult:
        res = IngestResult()
        refs = self._git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
        for ref in refs.split():
            branch = ref.split("/", 1)[1] if "/" in ref else ref
            if _skip_branch(branch):
                continue
            try:
                for path in self._git("ls-tree", "-r", "--name-only", ref).splitlines():
                    if _wanted(path, self.patterns):
                        res.files.append(LogFile(self.repo, branch, path,
                                                 self._git("show", f"{ref}:{path}")))
            except subprocess.CalledProcessError as e:
                res.errors.append(f"{branch}: git failed: {e.stderr.strip()}")
        return res


class GitHubSource:
    API = "https://api.github.com"

    def __init__(self, repo: str, token: str | None = None,
                 patterns: list[str] | None = None, max_retries: int = 4):
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.patterns = patterns or DEFAULT_PATTERNS
        self.max_retries = max_retries

    def _get(self, url: str):
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
        })
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                remaining = e.headers.get("X-RateLimit-Remaining")
                if e.code in (403, 429) and (remaining == "0" or e.code == 429):
                    reset = e.headers.get("Retry-After") or e.headers.get("X-RateLimit-Reset")
                    wait = delay
                    if reset and reset.isdigit():
                        wait = int(reset) if int(reset) < 1e6 else max(1, int(reset) - time.time())
                    if attempt < self.max_retries and wait <= 120:
                        time.sleep(wait)
                        delay *= 2
                        continue
                    raise RuntimeError(f"rate limited on {url}; retry after {wait:.0f}s") from e
                if e.code in (401, 403):
                    raise PermissionError(
                        f"token cannot read {self.repo} (HTTP {e.code}); "
                        "needs 'contents: read' on this repo") from e
                if e.code == 404:
                    raise FileNotFoundError(f"not found or no access: {url}") from e
                if e.code >= 500 and attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
            except urllib.error.URLError:
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

    def collect(self) -> IngestResult:
        res = IngestResult()
        branches, page = [], 1
        while True:
            batch = self._get(f"{self.API}/repos/{self.repo}/branches?per_page=100&page={page}")
            branches += [b["name"] for b in batch]
            if len(batch) < 100:
                break
            page += 1
        for b in branches:
            if _skip_branch(b):
                continue
            try:
                q = urllib.parse.quote(b, safe="")
                tree = self._get(f"{self.API}/repos/{self.repo}/git/trees/{q}?recursive=1")
                if tree.get("truncated"):
                    res.errors.append(f"{b}: file tree truncated, some logs may be missed")
                for node in tree.get("tree", []):
                    if node["type"] == "blob" and _wanted(node["path"], self.patterns):
                        blob = self._get(f"{self.API}/repos/{self.repo}/git/blobs/{node['sha']}")
                        text = base64.b64decode(blob["content"]).decode("utf-8", "replace")
                        res.files.append(LogFile(self.repo, b, node["path"], text))
            except (PermissionError, FileNotFoundError, RuntimeError) as e:
                res.errors.append(f"{b}: {e}")
        return res
