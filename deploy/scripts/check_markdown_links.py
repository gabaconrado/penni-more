#!/usr/bin/env python3
"""Check repository-local Markdown targets without contacting external hosts."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")


def anchor(text: str) -> str:
    value = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return re.sub(r"[\s-]+", "-", value)


def main() -> int:
    listed = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "*.md",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    failures: list[str] = []
    for relative in listed:
        source = ROOT / relative
        if not source.is_file():
            continue
        for raw in LINK.findall(source.read_text(encoding="utf-8")):
            target_text = raw.split(maxsplit=1)[0].strip("<>")
            if target_text.startswith(("http://", "https://", "mailto:")):
                continue
            path_text, _, fragment = target_text.partition("#")
            target = (
                source
                if not path_text
                else (source.parent / unquote(path_text)).resolve()
            )
            if not target.exists() or ROOT not in target.parents and target != ROOT:
                failures.append(f"{relative}: missing local target {target_text}")
                continue
            if (
                fragment
                and target.is_file()
                and target.suffix.lower() in {".md", ".markdown"}
            ):
                headings = {
                    anchor(line.lstrip("#"))
                    for line in target.read_text(encoding="utf-8").splitlines()
                    if line.startswith("#")
                }
                if unquote(fragment) not in headings:
                    failures.append(f"{relative}: missing anchor {target_text}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
