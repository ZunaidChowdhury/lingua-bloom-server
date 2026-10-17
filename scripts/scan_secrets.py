"""Fail if a secret-looking string appears in a repository file.

Patterns are split into fragments so this file never matches itself.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ALLOW_MARKER = "scan-" + "secrets: allow"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Groq API key", re.compile(r"g" + r"sk_[A-Za-z0-9_]{8,}")),
    ("database URL with password", re.compile(r"postgre" + r"sql://[^:/\s]+:[^@\s]+@")),
    ("JWT-like token", re.compile(r"ey" + r"J[A-Za-z0-9_-]{8,}\.")),
]


def _file_list() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    findings: list[str] = []
    for name in _file_list():
        path = Path(name)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(f"{name}:{number}: {label}")
    for finding in findings:
        print(finding)
    if findings:
        print(f"Secret scan failed: {len(findings)} finding(s).", file=sys.stderr)
        return 1
    print("Secret scan passed: no secrets found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
