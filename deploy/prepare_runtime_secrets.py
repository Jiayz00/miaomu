#!/usr/bin/env python3
"""Create the nursery inquiry HMAC secret without exposing its value.

The script is intentionally limited to the two contracted external secret
roots. Existing files are never opened or replaced: only metadata is checked,
so redeployments preserve the key that protects historical inquiry data.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import sys
import tempfile


SECRET_NAME = "nursery_inquiry_hmac_key"
SECRET_MODE = 0o440
SCOPES = {
    "main": Path("/etc/miaomu"),
    "restore": Path("/etc/miaomu-restore"),
}

RELEASE_ROOT = Path("/root/jia/miaomu")
CONFIG_NAMES = {
    "main": "database.php.example",
    "restore": "database.restore.php.example",
}


class SecretContractError(RuntimeError):
    """Raised when an external secret path does not satisfy the contract."""


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SecretContractError(f"cannot stat {path}") from exc


def _ensure_directory(path: Path) -> None:
    metadata = _lstat(path)
    if metadata is None:
        try:
            path.mkdir(mode=0o750)
            os.chown(path, 0, 0)
        except OSError as exc:
            raise SecretContractError(f"cannot create external directory {path}") from exc
        metadata = _lstat(path)
    if metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SecretContractError(f"external directory is not a real directory: {path}")
    if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
        raise SecretContractError(f"external directory permissions are unsafe: {path}")


def _validate_existing(path: Path) -> None:
    metadata = _lstat(path)
    if metadata is None:
        raise SecretContractError(f"secret disappeared during validation: {path}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SecretContractError(f"secret must be a regular file: {path}")
    if metadata.st_uid != 0 or metadata.st_gid != 10001:
        raise SecretContractError(f"secret ownership is unsafe: {path}")
    if stat.S_IMODE(metadata.st_mode) != SECRET_MODE:
        raise SecretContractError(f"secret mode must be 0440: {path}")
    if not 32 <= metadata.st_size <= 4097:
        raise SecretContractError(f"secret size is outside the contract: {path}")


def _validate_external_file(
    path: Path,
    *,
    mode: int,
    label: str,
    expected_uid: int = 0,
    expected_gid: int = 10001,
) -> None:
    """Validate metadata only; never read an external runtime file."""
    metadata = _lstat(path)
    if metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SecretContractError(f"{label} must be a regular file: {path}")
    if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
        raise SecretContractError(f"{label} ownership is unsafe: {path}")
    if stat.S_IMODE(metadata.st_mode) != mode or metadata.st_size <= 0:
        raise SecretContractError(f"{label} metadata is unsafe: {path}")


def _ensure_file_parent(path: Path) -> None:
    parent = path.parent
    _ensure_directory(parent)


def _copy_config_if_missing(scope: str, root: Path) -> str:
    target = root / "config" / "database.php"
    metadata = _lstat(target)
    if metadata is not None:
        _validate_external_file(target, mode=0o440, label="database config")
        return "preserved"

    template = RELEASE_ROOT / "deploy" / "config" / CONFIG_NAMES[scope]
    template_stat = _lstat(template)
    if (
        template_stat is None
        or stat.S_ISLNK(template_stat.st_mode)
        or not stat.S_ISREG(template_stat.st_mode)
    ):
        raise SecretContractError(f"database template is unavailable: {template}")
    _ensure_file_parent(target)
    # Build the file in an exclusive, same-directory inode and publish it with
    # a hard-link.  ``os.replace`` would overwrite a target that appeared
    # after the initial lstat (and a fixed ``.tmp`` name could be a symlink),
    # so the final link must fail closed when another process wins the race.
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".database.php.", dir=str(target.parent)
        )
        temporary = Path(temporary_name)
        os.fchown(descriptor, 0, 10001)
        os.fchmod(descriptor, 0o440)
        with template.open("rb") as source, os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        temporary_stat = _lstat(temporary)
        if (
            temporary_stat is None
            or stat.S_ISLNK(temporary_stat.st_mode)
            or not stat.S_ISREG(temporary_stat.st_mode)
            or temporary_stat.st_uid != 0
            or temporary_stat.st_gid != 10001
            or stat.S_IMODE(temporary_stat.st_mode) != 0o440
            or temporary_stat.st_size <= 0
        ):
            raise SecretContractError("database config temporary file metadata is unsafe")
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError:
            _validate_external_file(target, mode=0o440, label="database config")
            return "preserved"
    except OSError as exc:
        raise SecretContractError(f"cannot create database config: {target}") from exc
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
    _validate_external_file(target, mode=0o440, label="database config")
    return "created"


def _create_event_if_missing(root: Path) -> str:
    target = root / "generated" / "event.php"
    metadata = _lstat(target)
    if metadata is not None:
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SecretContractError(f"event bootstrap file must be a regular file: {target}")
        if metadata.st_uid != 0 or metadata.st_gid != 10001:
            raise SecretContractError(f"event bootstrap file ownership is unsafe: {target}")
        current_mode = stat.S_IMODE(metadata.st_mode)
        if current_mode not in (0o440, 0o660) or metadata.st_size <= 0:
            raise SecretContractError(f"event bootstrap file metadata is unsafe: {target}")
        if current_mode == 0o440:
            try:
                os.chmod(target, 0o660)
            except OSError as exc:
                raise SecretContractError(f"cannot reopen generated event for bootstrap: {target}") from exc
            return "reopened"
        return "preserved"

    _ensure_file_parent(target)
    payload = b"<?php\nreturn [];\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(target, flags, 0o660)
        os.fchown(descriptor, 0, 10001)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o660)
    except FileExistsError:
        _validate_external_file(target, mode=0o660, label="event bootstrap file")
        return "preserved"
    except OSError as exc:
        raise SecretContractError(f"cannot create event bootstrap file: {target}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _validate_external_file(target, mode=0o660, label="event bootstrap file")
    return "created"


def _finalize_event(root: Path) -> str:
    target = root / "generated" / "event.php"
    _validate_external_file(target, mode=0o660, label="event bootstrap file")
    try:
        os.chmod(target, 0o440)
    except OSError as exc:
        raise SecretContractError(f"cannot finalize generated event: {target}") from exc
    _validate_external_file(target, mode=0o440, label="generated event")
    return "finalized"


def _create_if_missing(path: Path) -> str:
    metadata = _lstat(path)
    if metadata is not None:
        _validate_existing(path)
        return "preserved"

    payload = (secrets.token_hex(32) + "\n").encode("ascii")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, SECRET_MODE)
        os.fchown(descriptor, 0, 10001)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.fchmod(descriptor, SECRET_MODE)
    except FileExistsError:
        _validate_existing(path)
        return "preserved"
    except OSError as exc:
        raise SecretContractError(f"cannot create secret {path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    try:
        _validate_existing(path)
    except SecretContractError:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return "created"


def prepare(
    scope: str,
    *,
    prepare_event: bool = False,
    prepare_config: bool = False,
    finalize_event: bool = False,
) -> dict[str, str]:
    if scope not in SCOPES:
        raise SecretContractError("scope must be main or restore")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise SecretContractError("secret preparation must run as root")

    root = SCOPES[scope]
    _ensure_directory(root)
    secret_dir = root / "secrets"
    _ensure_directory(secret_dir)
    action = _create_if_missing(secret_dir / SECRET_NAME)
    # Database credentials are provisioned outside the repository.  Check
    # their metadata here without opening either file, so a bad owner/mode is
    # rejected before Compose can create or reuse a database volume.
    _validate_external_file(
        secret_dir / "mysql_app_password",
        mode=SECRET_MODE,
        label="application database secret",
    )
    _validate_external_file(
        secret_dir / "mysql_root_password",
        mode=0o400,
        label="root database secret",
        expected_gid=0,
    )
    result: dict[str, str] = {
        "status": "pass",
        "scope": scope,
        "secret": SECRET_NAME,
        "action": action,
    }
    if prepare_config:
        result["config"] = _copy_config_if_missing(scope, root)
    if prepare_event:
        result["event"] = _create_event_if_missing(root)
    if finalize_event:
        result["event_finalize"] = _finalize_event(root)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=tuple(SCOPES), required=True)
    parser.add_argument("--prepare-event", action="store_true")
    parser.add_argument("--prepare-config", action="store_true")
    parser.add_argument("--finalize-event", action="store_true")
    args = parser.parse_args(argv)
    if not (args.prepare_event or args.prepare_config or args.finalize_event):
        parser.error("at least one preparation/finalization action is required")
    try:
        result = prepare(
            args.scope,
            prepare_event=args.prepare_event,
            prepare_config=args.prepare_config,
            finalize_event=args.finalize_event,
        )
    except SecretContractError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
