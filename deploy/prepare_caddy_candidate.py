#!/usr/bin/env python3
"""Build a deterministic Caddyfile candidate from the saved shared config."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys


MARKER = "# BEGIN MIAOMU NURsery CONTRACT"


def _real_regular(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing Caddy input: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"Caddy input must be a regular file: {path}")


def build(source: Path, fragment: Path, output: Path) -> None:
    _real_regular(source)
    _real_regular(fragment)
    source_text = source.read_text(encoding="utf-8")
    fragment_text = fragment.read_text(encoding="utf-8")
    if MARKER in source_text:
        raise RuntimeError("shared Caddyfile already contains the managed candidate marker")
    if "http://127.0.0.1:88" not in fragment_text:
        raise RuntimeError("Miaomu fragment must contain the loopback :88 site")

    parent = output.parent
    parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    if parent.is_symlink():
        raise RuntimeError("candidate output directory must not be a symlink")
    temporary = output.with_name(output.name + ".tmp")
    payload = source_text.rstrip() + "\n\n" + MARKER + "\n" + fragment_text.lstrip()
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, output)
    os.chmod(output, 0o440)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/root/jia/caddy/Caddyfile"))
    parser.add_argument("--fragment", type=Path, default=Path("/root/jia/miaomu/deploy/Caddyfile.miaomu"))
    parser.add_argument("--output", type=Path, default=Path("/root/jia/miaomu/.ops/Caddyfile.candidate"))
    args = parser.parse_args(argv)
    try:
        build(args.source, args.fragment, args.output)
    except (OSError, UnicodeError, RuntimeError) as exc:
        print(f"caddy candidate failed: {exc}", file=sys.stderr)
        return 1
    print("caddy candidate prepared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
