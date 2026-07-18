#!/usr/bin/env python3
"""Build a deterministic Caddyfile candidate from the saved shared config."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile


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
    payload = source_text.rstrip() + "\n\n" + MARKER + "\n" + fragment_text.lstrip()
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", dir=str(parent)
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o440)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output, follow_symlinks=False)
        metadata = output.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("published Caddy candidate is not a regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o440:
            raise RuntimeError("published Caddy candidate mode is unsafe")
    except FileExistsError as exc:
        raise RuntimeError("Caddy candidate output already exists") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


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
