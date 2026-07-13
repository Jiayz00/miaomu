#!/usr/bin/env python3
"""Validate immutable, non-secret inputs before the L4 release broker runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ValidationError(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ValidationError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return data


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def is_sha256(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.removeprefix("sha256:")
    return bool(SHA_RE.fullmatch(normalized)) and normalized != "0" * 64


def volume_name(compose: dict[str, Any], key: str) -> Any:
    value = compose.get("volumes", {}).get(key, {})
    return value.get("name") if isinstance(value, dict) else None


def service_mounts(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mounts: dict[str, dict[str, Any]] = {}
    for item in service.get("volumes", []):
        if isinstance(item, dict) and isinstance(item.get("target"), str):
            mounts[item["target"]] = item
    return mounts


def validate_mount(
    mount: dict[str, Any],
    label: str,
    *,
    mount_type: str,
    source: str,
    target: str,
    read_only: bool,
) -> list[str]:
    errors: list[str] = []
    require(mount.get("type") == mount_type, f"{label} mount type mismatch", errors)
    require(mount.get("source") == source, f"{label} mount source mismatch", errors)
    require(mount.get("target") == target, f"{label} mount target mismatch", errors)
    if mount_type == "bind":
        require(
            set(mount) == {"type", "source", "target", "read_only", "bind"},
            f"{label} bind mount keys mismatch",
            errors,
        )
        require(mount.get("read_only") is read_only, f"{label} read-only mode mismatch", errors)
        require(
            mount.get("bind") == {"create_host_path": False},
            f"{label} bind mount must disable create_host_path",
            errors,
        )
    else:
        require(set(mount) == {"type", "source", "target"}, f"{label} volume mount keys mismatch", errors)
        require(not read_only, f"{label} named volume cannot be read-only by this contract", errors)
    return errors


def validate_compose_contract(
    main: dict[str, Any], restore: dict[str, Any], policy: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    expected_services = {"app", "db"}
    require(main.get("name") == "miaomu", "main Compose project must be miaomu", errors)
    require(
        restore.get("name") == "miaomu_restore",
        "restore Compose project must be miaomu_restore",
        errors,
    )

    for label, compose in (("main", main), ("restore", restore)):
        require(
            set(compose) == {"name", "services", "networks", "volumes", "secrets"},
            f"{label} Compose top-level keys mismatch",
            errors,
        )
        services = compose.get("services")
        require(isinstance(services, dict), f"{label} services must be an object", errors)
        if not isinstance(services, dict):
            continue
        require(set(services) == expected_services, f"{label} services must be app and db only", errors)
        networks = compose.get("networks", {})
        require(set(networks) == {"backend"}, f"{label} must define only the backend network", errors)
        network = networks.get("backend", {})
        require(network.get("internal") is True, f"{label} backend must be internal", errors)
        expected_network_name = "miaomu_backend" if label == "main" else "miaomu_restore_backend"
        require(network.get("name") == expected_network_name, f"{label} backend name mismatch", errors)
        require(
            set(compose.get("volumes", {})) == {"runtime", "uploads", "downloads", "fpm_socket", "db_data"},
            f"{label} named volume set mismatch",
            errors,
        )
        volume_prefix = "miaomu" if label == "main" else "miaomu_restore"
        for volume_key in ("runtime", "uploads", "downloads", "fpm_socket", "db_data"):
            require(
                compose.get("volumes", {}).get(volume_key) == {"name": f"{volume_prefix}_{volume_key}"},
                f"{label} {volume_key} top-level volume definition mismatch",
                errors,
            )
        require(
            set(compose.get("secrets", {})) == {"mysql_app_password", "mysql_root_password"},
            f"{label} secret set mismatch",
            errors,
        )
        for service_name in expected_services:
            service = services.get(service_name, {})
            mount_items = service.get("volumes", [])
            mount_targets = [item.get("target") for item in mount_items if isinstance(item, dict)]
            require(
                len(mount_targets) == len(mount_items)
                and all(isinstance(target, str) and target for target in mount_targets),
                f"{label}.{service_name} mounts must use structured non-empty targets",
                errors,
            )
            require(
                len(mount_targets) == len(set(mount_targets)),
                f"{label}.{service_name} contains duplicate mount targets",
                errors,
            )
            require("ports" not in service, f"{label}.{service_name} must not publish ports", errors)
            require("expose" not in service, f"{label}.{service_name} must not expose ports", errors)
            require("network_mode" not in service, f"{label}.{service_name} must not set network_mode", errors)
            require(
                service.get("networks") == ["backend"],
                f"{label}.{service_name} must join only backend",
                errors,
            )
            require(
                "/var/run/docker.sock" not in json.dumps(service, sort_keys=True),
                f"{label}.{service_name} must not mount the Docker socket",
                errors,
            )
            require(service.get("read_only") is True, f"{label}.{service_name} must be read-only", errors)
            require(
                service.get("cap_drop") == ["ALL"],
                f"{label}.{service_name} must drop all capabilities",
                errors,
            )
            require(
                "no-new-privileges:true" in service.get("security_opt", []),
                f"{label}.{service_name} must enable no-new-privileges",
                errors,
            )
            labels = service.get("labels", {})
            require(
                labels.get("com.centurylinklabs.watchtower.enable") == "false",
                f"{label}.{service_name} must opt out of Watchtower",
                errors,
            )
        app = services.get("app", {})
        app_keys = {
            "image",
            "platform",
            "user",
            "init",
            "read_only",
            "restart",
            "pull_policy",
            "depends_on",
            "environment",
            "secrets",
            "volumes",
            "networks",
            "healthcheck",
            "cap_drop",
            "security_opt",
            "tmpfs",
            "pids_limit",
            "cpus",
            "mem_limit",
            "logging",
            "labels",
        }
        if label == "main":
            app_keys.update({"build", "stop_grace_period"})
        require(set(app) == app_keys, f"{label}.app keys mismatch", errors)
        require(app.get("user") == "10001:10001", f"{label}.app must run as 10001:10001", errors)
        require("group_add" not in app, f"{label}.app must not gain supplemental groups", errors)
        require("cap_add" not in app, f"{label}.app must not add capabilities", errors)
        app_mounts = service_mounts(app)
        expected_config = (
            "/etc/miaomu/config/database.php"
            if label == "main"
            else "/etc/miaomu-restore/config/database.php"
        )
        require(
            set(app_mounts) == {
                "/var/www/html/config/database.php",
                "/var/www/html/app/event.php",
                "/var/www/html/runtime",
                "/var/www/html/public/static/upload",
                "/var/www/html/public/download",
                "/run/miaomu-fpm",
            },
            f"{label}.app mount targets mismatch",
            errors,
        )
        errors.extend(
            validate_mount(
                app_mounts.get("/var/www/html/config/database.php", {}),
                f"{label}.app database config",
                mount_type="bind",
                source=expected_config,
                target="/var/www/html/config/database.php",
                read_only=True,
            )
        )
        expected_event = (
            "/etc/miaomu/generated/event.php"
            if label == "main"
            else "/etc/miaomu-restore/generated/event.php"
        )
        errors.extend(
            validate_mount(
                app_mounts.get("/var/www/html/app/event.php", {}),
                f"{label}.app generated event",
                mount_type="bind",
                source=expected_event,
                target="/var/www/html/app/event.php",
                read_only=True,
            )
        )
        expected_app_sources = {
            "/var/www/html/runtime": "runtime",
            "/var/www/html/public/static/upload": "uploads",
            "/var/www/html/public/download": "downloads",
            "/run/miaomu-fpm": "fpm_socket",
        }
        for target_path, source_name in expected_app_sources.items():
            errors.extend(
                validate_mount(
                    app_mounts.get(target_path, {}),
                    f"{label}.app {source_name}",
                    mount_type="volume",
                    source=source_name,
                    target=target_path,
                    read_only=False,
                )
            )
        require(
            app.get("secrets") == ["mysql_app_password"],
            f"{label}.app must receive only the application database secret",
            errors,
        )
        expected_app_image = (
            "miaomu-app:${MIAOMU_RELEASE_SHA:?set a 40-character release commit}"
            if label == "main"
            else "miaomu-app:${MIAOMU_RESTORE_RELEASE_SHA:?set the restored release commit}"
        )
        require(app.get("image") == expected_app_image, f"{label}.app image contract mismatch", errors)
        require(app.get("platform") == "linux/amd64", f"{label}.app platform mismatch", errors)
        require(app.get("init") is True, f"{label}.app must use an init process", errors)
        require(
            app.get("restart") == ("unless-stopped" if label == "main" else "no"),
            f"{label}.app restart policy mismatch",
            errors,
        )
        require(app.get("pull_policy") == "never", f"{label}.app pull policy mismatch", errors)
        require(
            app.get("depends_on") == {"db": {"condition": "service_healthy"}},
            f"{label}.app must wait for healthy db",
            errors,
        )
        expected_release_variable = (
            "${MIAOMU_RELEASE_SHA:?set a 40-character release commit}"
            if label == "main"
            else "${MIAOMU_RESTORE_RELEASE_SHA:?set the restored release commit}"
        )
        require(
            app.get("environment")
            == {
                "MIAOMU_ENV": "production" if label == "main" else "restore",
                "MIAOMU_RELEASE_SHA": expected_release_variable,
                "TZ": "Asia/Shanghai",
            },
            f"{label}.app environment mismatch",
            errors,
        )
        require(
            app.get("healthcheck", {}).get("test")
            == ["CMD", "php", "/usr/local/lib/miaomu/environment_check.php", "--health"],
            f"{label}.app healthcheck mismatch",
            errors,
        )
        if label == "main":
            require(
                app.get("build")
                == {
                    "context": "..",
                    "dockerfile": "deploy/docker/app/Dockerfile",
                    "target": "runtime",
                    "args": {"MIAOMU_RELEASE_SHA": expected_release_variable},
                },
                "main app build contract mismatch",
                errors,
            )

        db = services.get("db", {})
        db_keys = {
            "image",
            "platform",
            "entrypoint",
            "command",
            "read_only",
            "restart",
            "pull_policy",
            "environment",
            "secrets",
            "volumes",
            "networks",
            "healthcheck",
            "cap_drop",
            "cap_add",
            "security_opt",
            "tmpfs",
            "pids_limit",
            "cpus",
            "mem_limit",
            "logging",
            "labels",
        }
        if label == "main":
            db_keys.add("stop_grace_period")
        require(set(db) == db_keys, f"{label}.db keys mismatch", errors)
        require("user" not in db, f"{label}.db must start through the audited root bootstrap wrapper", errors)
        require("group_add" not in db, f"{label}.db must not receive supplemental group 10001", errors)
        require(
            db.get("entrypoint") == ["/bin/sh", "/usr/local/bin/miaomu-mysql-entrypoint"],
            f"{label}.db entrypoint mismatch",
            errors,
        )
        require(
            set(db.get("cap_add", [])) == {"CHOWN", "SETGID", "SETUID"},
            f"{label}.db bootstrap capabilities must be CHOWN, SETGID and SETUID only",
            errors,
        )
        db_mounts = service_mounts(db)
        require(
            set(db_mounts) == {
                "/usr/local/bin/miaomu-mysql-entrypoint",
                "/usr/local/bin/miaomu-mysql-healthcheck",
                "/var/lib/mysql",
            },
            f"{label}.db mount targets mismatch",
            errors,
        )
        errors.extend(
            validate_mount(
                db_mounts.get("/usr/local/bin/miaomu-mysql-entrypoint", {}),
                f"{label}.db wrapper",
                mount_type="bind",
                source="./mysql-entrypoint.sh",
                target="/usr/local/bin/miaomu-mysql-entrypoint",
                read_only=True,
            )
        )
        errors.extend(
            validate_mount(
                db_mounts.get("/usr/local/bin/miaomu-mysql-healthcheck", {}),
                f"{label}.db healthcheck",
                mount_type="bind",
                source="./mysql-healthcheck.sh",
                target="/usr/local/bin/miaomu-mysql-healthcheck",
                read_only=True,
            )
        )
        require(
            set(db.get("secrets", [])) == {"mysql_app_password", "mysql_root_password"},
            f"{label}.db secret set mismatch",
            errors,
        )
        require(
            any(str(value).startswith("/run/miaomu-db-secrets:") and "mode=0700" in str(value) for value in db.get("tmpfs", [])),
            f"{label}.db must use a root-only private secret tmpfs",
            errors,
        )
        require(
            db.get("healthcheck", {}).get("test", [])
            == ["CMD", "/bin/sh", "/usr/local/bin/miaomu-mysql-healthcheck", "steady"],
            f"{label}.db base healthcheck must require steady mode",
            errors,
        )
        require(
            db.get("image") == policy.get("images", {}).get("mysql", {}).get("reference"),
            f"{label}.db image must match stack policy",
            errors,
        )
        require(db.get("platform") == "linux/amd64", f"{label}.db platform mismatch", errors)
        require(
            db.get("command")
            == [
                "mysqld",
                "--character-set-server=utf8mb4",
                "--collation-server=utf8mb4_unicode_ci",
                "--default-time-zone=+08:00",
                "--local-infile=0",
                "--max-connections=100",
                "--skip-name-resolve",
            ],
            f"{label}.db command mismatch",
            errors,
        )
        require(
            db.get("restart") == ("unless-stopped" if label == "main" else "no"),
            f"{label}.db restart policy mismatch",
            errors,
        )
        require(db.get("pull_policy") == "never", f"{label}.db pull policy mismatch", errors)
        expected_db_name = "miaomu" if label == "main" else "miaomu_restore"
        expected_db_user = "miaomu_app" if label == "main" else "miaomu_restore_app"
        require(
            db.get("environment")
            == {
                "MYSQL_DATABASE": expected_db_name,
                "MYSQL_USER": expected_db_user,
                "MYSQL_PASSWORD_FILE": "/run/secrets/mysql_app_password",
                "MYSQL_ROOT_PASSWORD_FILE": "/run/secrets/mysql_root_password",
                "TZ": "Asia/Shanghai",
            },
            f"{label}.db environment mismatch",
            errors,
        )
        errors.extend(
            validate_mount(
                db_mounts.get("/var/lib/mysql", {}),
                f"{label}.db data",
                mount_type="volume",
                source="db_data",
                target="/var/lib/mysql",
                read_only=False,
            )
        )

        secret_root = "/etc/miaomu/secrets" if label == "main" else "/etc/miaomu-restore/secrets"
        for secret_name in ("mysql_app_password", "mysql_root_password"):
            require(
                compose.get("secrets", {}).get(secret_name, {}).get("file")
                == f"{secret_root}/{secret_name}",
                f"{label} external secret path mismatch for {secret_name}",
                errors,
            )
    require(
        volume_name(main, "fpm_socket") == "miaomu_fpm_socket",
        "main socket volume name mismatch",
        errors,
    )
    require(
        volume_name(restore, "fpm_socket") == "miaomu_restore_fpm_socket",
        "restore socket volume name mismatch",
        errors,
    )
    require(
        volume_name(main, "fpm_socket") != volume_name(restore, "fpm_socket"),
        "main and restore socket volumes must be isolated",
        errors,
    )
    for key in ("runtime", "uploads", "downloads", "fpm_socket", "db_data"):
        require(
            volume_name(main, key) != volume_name(restore, key),
            f"main and restore {key} volumes must be isolated",
            errors,
        )

    target = policy.get("target", {})
    require(target.get("main_project") == main.get("name"), "policy main project mismatch", errors)
    require(target.get("restore_project") == restore.get("name"), "policy restore project mismatch", errors)
    socket = policy.get("fpm_socket", {})
    require(socket.get("main_volume") == volume_name(main, "fpm_socket"), "policy main socket mismatch", errors)
    require(
        socket.get("restore_volume") == volume_name(restore, "fpm_socket"),
        "policy restore socket mismatch",
        errors,
    )
    require(socket.get("container_path") == "/run/miaomu-fpm/php-fpm.sock", "socket path mismatch", errors)
    require(socket.get("gid") == 10001, "socket GID must be 10001", errors)
    require(socket.get("mode") == "0660", "socket mode must be 0660", errors)
    identities = policy.get("service_identities", {})
    require(
        identities.get("app", {}).get("supplemental_groups") == [],
        "policy app supplemental groups must be empty",
        errors,
    )
    require(
        identities.get("db", {}).get("supplemental_groups") == [],
        "policy db supplemental groups must be empty",
        errors,
    )
    require(
        identities.get("db", {}).get("steady_marker") == "/var/lib/mysql/.miaomu-steady",
        "policy db steady marker mismatch",
        errors,
    )
    require(
        identities.get("db", {}).get("bootstrap_health_overlays")
        == ["compose.bootstrap.yaml", "compose.restore.bootstrap.yaml"],
        "policy db bootstrap overlays mismatch",
        errors,
    )
    require(
        identities.get("db", {}).get("steady_health_mode") == "steady",
        "policy db steady health mode mismatch",
        errors,
    )
    require(
        set(identities.get("db", {}).get("bootstrap_capabilities", [])) == {"CHOWN", "SETGID", "SETUID"},
        "policy db bootstrap capabilities mismatch",
        errors,
    )
    expected_external = {
        "external_files": {
            "database_config": "/etc/miaomu/config/database.php",
            "mysql_app_password": "/etc/miaomu/secrets/mysql_app_password",
            "mysql_root_password": "/etc/miaomu/secrets/mysql_root_password",
            "generated_event": "/etc/miaomu/generated/event.php",
            "shared_required_uid": 0,
            "shared_required_gid": 10001,
            "shared_required_mode": "0440",
            "root_secret_required_uid": 0,
            "root_secret_required_gid": 0,
            "root_secret_required_mode": "0400",
        },
        "restore_external_files": {
            "database_config": "/etc/miaomu-restore/config/database.php",
            "mysql_app_password": "/etc/miaomu-restore/secrets/mysql_app_password",
            "mysql_root_password": "/etc/miaomu-restore/secrets/mysql_root_password",
            "generated_event": "/etc/miaomu-restore/generated/event.php",
            "shared_required_uid": 0,
            "shared_required_gid": 10001,
            "shared_required_mode": "0440",
            "root_secret_required_uid": 0,
            "root_secret_required_gid": 0,
            "root_secret_required_mode": "0400",
        },
    }
    for key, expected_value in expected_external.items():
        require(policy.get(key) == expected_value, f"policy {key} mismatch", errors)
    require(
        policy.get("event_generation") == {
            "target": "/var/www/html/app/event.php",
            "initializer": "/usr/local/lib/miaomu/nursery-bootstrap.php",
            "bootstrap_mode": "0660",
            "steady_mode": "0440",
            "owner_uid": 0,
            "group_gid": 10001,
            "allowed_enabled_plugins": ["nursery"],
            "official_service": "app\\service\\PluginsAdminService",
            "requires_read_only_restart": True,
        },
        "policy event generation contract mismatch",
        errors,
    )
    return errors


def validate_init_overlays(main: dict[str, Any], restore: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = (
        ("main", main, "miaomu", "/etc/miaomu/generated/event.php"),
        ("restore", restore, "miaomu_restore", "/etc/miaomu-restore/generated/event.php"),
    )
    for label, overlay, project, source in expected:
        require(overlay.get("name") == project, f"{label} init project mismatch", errors)
        require(set(overlay.get("services", {})) == {"app"}, f"{label} init overlay may modify app only", errors)
        app = overlay.get("services", {}).get("app", {})
        require(set(app) == {"restart", "volumes"}, f"{label} init app override contains extra keys", errors)
        require(app.get("restart") == "no", f"{label} init app must not restart", errors)
        mounts = app.get("volumes", [])
        require(len(mounts) == 1 and isinstance(mounts[0], dict), f"{label} init mount set mismatch", errors)
        if len(mounts) == 1 and isinstance(mounts[0], dict):
            mount = mounts[0]
            require(mount.get("type") == "bind", f"{label} init event must be a bind mount", errors)
            require(mount.get("source") == source, f"{label} init event source mismatch", errors)
            require(mount.get("target") == "/var/www/html/app/event.php", f"{label} init event target mismatch", errors)
            require(mount.get("read_only") is False, f"{label} init event must be writable", errors)
            require(
                mount.get("bind", {}).get("create_host_path") is False,
                f"{label} init event source must already exist",
                errors,
            )
    return errors


def validate_bootstrap_overlays(main: dict[str, Any], restore: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = (("main", main, "miaomu"), ("restore", restore, "miaomu_restore"))
    for label, overlay, project in expected:
        require(overlay.get("name") == project, f"{label} bootstrap project mismatch", errors)
        require(set(overlay.get("services", {})) == {"db"}, f"{label} bootstrap overlay may modify db only", errors)
        db = overlay.get("services", {}).get("db", {})
        require(set(db) == {"restart", "healthcheck"}, f"{label} bootstrap db override contains extra keys", errors)
        require(db.get("restart") == "no", f"{label} bootstrap db must not restart", errors)
        health = db.get("healthcheck", {})
        require(
            health.get("test")
            == ["CMD", "/bin/sh", "/usr/local/bin/miaomu-mysql-healthcheck", "bootstrap"],
            f"{label} bootstrap health mode mismatch",
            errors,
        )
        require(
            {"interval", "timeout", "retries", "start_period"}.issubset(health),
            f"{label} bootstrap health bounds missing",
            errors,
        )
    return errors


def validate_caddy_mounts(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require(contract.get("service") == "jia-caddy", "Caddy service must be jia-caddy", errors)
    require(contract.get("required_caddy_version") == "2.11.2", "Caddy version must be 2.11.2", errors)
    require(contract.get("required_network_mode") == "host", "Caddy must retain host network", errors)
    require(contract.get("supplemental_groups") == [10001], "Caddy supplemental group must be 10001", errors)
    mounts = contract.get("mounts", [])
    targets = {item.get("target"): item for item in mounts if isinstance(item, dict)}
    require(set(targets) == {
        "/var/www/html/public",
        "/var/www/html/public/static/upload",
        "/run/miaomu-fpm",
    }, "Caddy must receive exactly public, uploads and socket mounts", errors)
    for target, item in targets.items():
        require(item.get("read_only") is True, f"Caddy mount {target} must be read-only", errors)
    expected_mounts = {
        "/var/www/html/public": ("bind", "/root/jia/miaomu/public"),
        "/var/www/html/public/static/upload": ("volume", "miaomu_uploads"),
        "/run/miaomu-fpm": ("volume", "miaomu_fpm_socket"),
    }
    for target, (mount_type, source) in expected_mounts.items():
        item = targets.get(target, {})
        require(item.get("type") == mount_type, f"Caddy mount type mismatch for {target}", errors)
        require(item.get("source") == source, f"Caddy mount source mismatch for {target}", errors)
    require(
        targets.get("/run/miaomu-fpm", {}).get("source") == "miaomu_fpm_socket",
        "Caddy socket volume mismatch",
        errors,
    )
    serialized = json.dumps(mounts, sort_keys=True)
    for forbidden in ("miaomu_downloads", "miaomu_runtime", "miaomu_db_data", "/var/run/docker.sock"):
        require(forbidden not in serialized, f"Caddy mounts forbidden source {forbidden}", errors)
    strategy = contract.get("change_strategy", {})
    require(strategy.get("shared_stack_down_allowed") is False, "shared Caddy stack down must remain forbidden", errors)
    require(
        "recreate only jia-caddy" in str(strategy.get("new_mount_or_group", "")),
        "new Caddy mounts or group must require a jia-caddy-only recreate",
        errors,
    )
    require(
        "reload" in str(strategy.get("configuration_only_when_all_mounts_and_group_exist", "")),
        "configuration-only Caddy changes must require reload",
        errors,
    )
    health = contract.get("required_health_checks", {})
    require(
        health == {
            "before_change": "https://supervise.jiayyy.cn",
            "after_change": "https://supervise.jiayyy.cn",
            "after_rollback": "https://supervise.jiayyy.cn",
        },
        "shared Caddy health gates mismatch",
        errors,
    )
    return errors


def validate_caddy_fragment(source: str) -> list[str]:
    errors: list[str] = []
    require("http://127.0.0.1:88 {" in source, "Caddy listener must be loopback HTTP port 88", errors)
    for forbidden in (
        "38.12.21.18:88",
        "0.0.0.0:88",
        "PHP_VALUE",
        "PHP_ADMIN_VALUE",
        ":80 {",
        ":443",
        "https://",
        "tls ",
    ):
        require(forbidden not in source, f"Caddy fragment contains forbidden token {forbidden}", errors)
    require("root * /var/www/html/public" in source, "Caddy public root mismatch", errors)
    require(
        source.count("php_fastcgi unix//run/miaomu-fpm/php-fpm.sock") == 4,
        "Caddy must use the fixed FPM socket in three entry handlers and one fallback",
        errors,
    )
    script_values = set(re.findall(r"env SCRIPT_FILENAME ([^\s]+)", source))
    require(
        script_values == {
            "/var/www/html/public/index.php",
            "/var/www/html/public/admin.php",
            "/var/www/html/public/api.php",
        },
        "Caddy SCRIPT_FILENAME allow-list mismatch",
        errors,
    )
    required_matchers = {
        "@download": ("path_regexp download", "(?i)^/download(?:/|$)"),
        "@sensitiveEntry": ("path_regexp sensitiveEntry", "(?i)^/(?:install|core|router)\\.php(?:/|$)"),
        "@hidden": ("path_regexp hidden", "(?i)(?:^|/)\\.[^/]+"),
        "@sensitivePath": ("path_regexp sensitivePath", "(?i)^/(?:app|config|extend|runtime|rsakeys|sourcecode|vendor)(?:/|$)"),
        "@aceDemo": ("path_regexp aceDemo", "(?i)^/static/common/lib/ace-builds/demo/.*\\.php(?:/|$)"),
        "@scriptLike": ("path_regexp scriptLike", "(?i)\\.(?:php[0-9]*|phtml|phar)(?:/|$)"),
    }
    static_index = source.find("@static file")
    file_server_index = source.find("file_server")
    require(static_index >= 0 and file_server_index > static_index, "Caddy file_server ordering is invalid", errors)
    for marker, fragments in required_matchers.items():
        declaration_index = source.find(marker)
        require(declaration_index >= 0, f"Caddy matcher missing: {marker}", errors)
        require(
            declaration_index >= 0 and static_index >= 0 and declaration_index < static_index,
            f"Caddy matcher must precede static serving: {marker}",
            errors,
        )
        require(f"respond {marker} 404" in source, f"Caddy matcher must return 404: {marker}", errors)
        for fragment in fragments:
            require(fragment in source, f"Caddy matcher {marker} is too broad or incomplete", errors)
    require("rewrite * /index.php" in source, "Caddy front-controller fallback missing", errors)
    return errors


def git_state(repository: Path) -> tuple[str, bool]:
    try:
        head = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(repository), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError(f"cannot inspect Git repository: {exc}") from exc
    return head, dirty


def validate_manifest(
    manifest: dict[str, Any],
    policy: dict[str, Any],
    repository: Path,
    expected_event_phase: str | None = None,
    expected_event_scope: str | None = None,
) -> list[str]:
    errors: list[str] = []
    require(manifest.get("schema_version") == 2, "manifest schema_version must be 2", errors)
    release_sha = manifest.get("release_sha")
    require(bool(GIT_SHA_RE.fullmatch(str(release_sha))), "manifest release_sha must be a full Git SHA", errors)
    head, dirty = git_state(repository)
    require(release_sha == head, "manifest release_sha must equal repository HEAD", errors)
    require(not dirty, "release repository must be clean", errors)
    require(manifest.get("target_platform") == policy.get("target", {}).get("platform"), "target platform mismatch", errors)
    require(
        manifest.get("projects") == {"main": "miaomu", "restore": "miaomu_restore"},
        "manifest project names mismatch",
        errors,
    )
    expected_socket = {
        "main_volume": "miaomu_fpm_socket",
        "restore_volume": "miaomu_restore_fpm_socket",
        "path": "/run/miaomu-fpm/php-fpm.sock",
        "gid": 10001,
        "mode": "0660",
    }
    require(manifest.get("socket") == expected_socket, "manifest socket contract mismatch", errors)
    require(is_sha256(manifest.get("database_config_sha256")), "database config SHA-256 missing", errors)
    require(
        is_sha256(manifest.get("restore_database_config_sha256")),
        "restore database config SHA-256 missing",
        errors,
    )
    generated_events = manifest.get("generated_events")
    require(isinstance(generated_events, dict), "manifest generated_events must be an object", errors)
    if expected_event_phase is not None:
        require(
            expected_event_scope in {"main", "restore", "both"},
            "manifest event phase validation requires a valid scope",
            errors,
        )
    if isinstance(generated_events, dict):
        require(set(generated_events) == {"main", "restore"}, "manifest generated event scopes mismatch", errors)
        required_scopes = (
            {"main", "restore"}
            if expected_event_scope == "both"
            else ({expected_event_scope} if expected_event_scope in {"main", "restore"} else set())
        )
        for scope in ("main", "restore"):
            event = generated_events.get(scope, {})
            require(isinstance(event, dict), f"{scope} generated event must be an object", errors)
            if not isinstance(event, dict):
                continue
            require(set(event) == {"state", "sha256"}, f"{scope} generated event keys mismatch", errors)
            inferred_phase = {"pending": "bootstrap", "generated": "steady"}.get(event.get("state"))
            require(inferred_phase is not None, f"{scope} generated event state must be pending or generated", errors)
            if scope in required_scopes and expected_event_phase is not None:
                require(inferred_phase == expected_event_phase, f"{scope} generated event phase mismatch", errors)
            if inferred_phase == "bootstrap":
                require(event.get("sha256") is None, f"pending {scope} event hash must be null", errors)
            elif inferred_phase == "steady":
                require(is_sha256(event.get("sha256")), f"{scope} generated event SHA-256 missing", errors)

    manifest_images = manifest.get("images", {})
    policy_images = policy.get("images", {})
    for key in ("php_base", "composer", "mysql"):
        item = manifest_images.get(key, {})
        require(item.get("reference") == policy_images.get(key, {}).get("reference"), f"{key} reference mismatch", errors)
        require(is_sha256(item.get("platform_digest")), f"{key} platform digest missing", errors)
        require(is_sha256(item.get("image_id")), f"{key} image ID missing", errors)
    app = manifest_images.get("app", {})
    require(app.get("reference") == f"miaomu-app:{release_sha}", "app image tag must include release SHA", errors)
    require(is_sha256(app.get("image_id")), "app image ID missing", errors)

    caddy = manifest.get("caddy", {})
    require(caddy.get("container") == "jia-caddy", "Caddy container mismatch", errors)
    require(caddy.get("version") == "2.11.2", "Caddy version mismatch", errors)
    require(is_sha256(caddy.get("config_sha256")), "Caddy config SHA-256 missing", errors)
    require(is_sha256(caddy.get("compose_sha256")), "Caddy Compose SHA-256 missing", errors)
    return errors


def validate_external_file_metadata(
    path: Path,
    label: str,
    *,
    expected_uid: int = 0,
    expected_gid: int = 10001,
    expected_mode: int = 0o440,
    require_nonempty: bool = True,
    allow_missing: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return [] if allow_missing else [f"{label} metadata unavailable: file does not exist"]
    except OSError as exc:
        return [f"{label} metadata unavailable: {exc}"]
    require(stat.S_ISREG(metadata.st_mode), f"{label} must be a regular file", errors)
    require(not path.is_symlink(), f"{label} must not be a symlink", errors)
    if require_nonempty:
        require(metadata.st_size > 0, f"{label} must be non-empty", errors)
    else:
        require(metadata.st_size == 0, f"{label} must be empty before generation", errors)
    require(getattr(metadata, "st_uid", None) == expected_uid, f"{label} owner UID mismatch", errors)
    require(getattr(metadata, "st_gid", None) == expected_gid, f"{label} group GID mismatch", errors)
    require(
        stat.S_IMODE(metadata.st_mode) == expected_mode,
        f"{label} mode must be {expected_mode:04o}",
        errors,
    )
    return errors


def validate_external_inputs(
    manifest: dict[str, Any],
    policy: dict[str, Any],
    template: Path,
    restore_template: Path,
    caddy_config: Path,
    caddy_compose: Path,
    event_phase: str,
    event_scope: str,
) -> list[str]:
    errors: list[str] = []
    require(event_phase in {"bootstrap", "steady"}, "external event phase is invalid", errors)
    require(event_scope in {"main", "restore", "both"}, "external event scope is invalid", errors)
    groups = (
        (
            "main",
            policy.get("external_files", {}),
            template,
            "database_config_sha256",
        ),
        (
            "restore",
            policy.get("restore_external_files", {}),
            restore_template,
            "restore_database_config_sha256",
        ),
    )
    selected_scopes = {"main", "restore"} if event_scope == "both" else {event_scope}
    for label, external, expected_template, manifest_key in groups:
        if label not in selected_scopes:
            continue
        database_config = Path(external.get("database_config", ""))
        app_secret = Path(external.get("mysql_app_password", ""))
        root_secret = Path(external.get("mysql_root_password", ""))
        generated_event = Path(external.get("generated_event", ""))
        group_errors: list[str] = []
        for path, item_label in (
            (database_config, f"{label} database config"),
            (app_secret, f"{label} application database secret"),
        ):
            group_errors.extend(validate_external_file_metadata(path, item_label))
        group_errors.extend(
            validate_external_file_metadata(
                root_secret,
                f"{label} root database secret",
                expected_gid=0,
                expected_mode=0o400,
            )
        )
        if event_phase == "bootstrap":
            group_errors.extend(
                validate_external_file_metadata(
                    generated_event,
                    f"{label} generated event",
                    expected_mode=0o660,
                    require_nonempty=False,
                    allow_missing=True,
                )
            )
        else:
            group_errors.extend(validate_external_file_metadata(generated_event, f"{label} generated event"))
        errors.extend(group_errors)
        if group_errors:
            continue
        try:
            require(
                database_config.read_bytes() == expected_template.read_bytes(),
                f"external {label} database.php must be byte-for-byte equal to its audited template",
                errors,
            )
            expected_hash = digest_file(expected_template)
            require(
                manifest.get(manifest_key) == expected_hash,
                f"manifest {label} database config SHA-256 mismatch",
                errors,
            )
            if event_phase == "steady":
                event_manifest = manifest.get("generated_events", {}).get(label, {})
                require(
                    event_manifest.get("sha256") == digest_file(generated_event),
                    f"manifest {label} generated event SHA-256 mismatch",
                    errors,
                )
        except OSError as exc:
            errors.append(f"cannot compare {label} database config template: {exc}")

    for path, key in ((caddy_config, "config_sha256"), (caddy_compose, "compose_sha256")):
        try:
            require(
                manifest.get("caddy", {}).get(key) == digest_file(path),
                f"manifest Caddy {key} mismatch",
                errors,
            )
        except OSError as exc:
            errors.append(f"cannot hash Caddy input {path}: {exc}")
    return errors


def parse_args() -> argparse.Namespace:
    deploy_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="L4 release manifest JSON")
    parser.add_argument("--repository-root", type=Path, default=deploy_dir.parent)
    parser.add_argument("--main-compose", type=Path, default=deploy_dir / "compose.yaml")
    parser.add_argument("--restore-compose", type=Path, default=deploy_dir / "compose.restore.yaml")
    parser.add_argument("--init-compose", type=Path, default=deploy_dir / "compose.init.yaml")
    parser.add_argument(
        "--restore-init-compose",
        type=Path,
        default=deploy_dir / "compose.restore.init.yaml",
    )
    parser.add_argument(
        "--bootstrap-compose",
        type=Path,
        default=deploy_dir / "compose.bootstrap.yaml",
    )
    parser.add_argument(
        "--restore-bootstrap-compose",
        type=Path,
        default=deploy_dir / "compose.restore.bootstrap.yaml",
    )
    parser.add_argument("--policy", type=Path, default=deploy_dir / "stack-policy.json")
    parser.add_argument("--caddy-mounts", type=Path, default=deploy_dir / "caddy-mounts.json")
    parser.add_argument("--database-template", type=Path, default=deploy_dir / "config" / "database.php.example")
    parser.add_argument(
        "--restore-database-template",
        type=Path,
        default=deploy_dir / "config" / "database.restore.php.example",
    )
    parser.add_argument("--caddy-fragment", type=Path, default=deploy_dir / "Caddyfile.miaomu")
    parser.add_argument("--check-external", action="store_true")
    parser.add_argument("--external-phase", choices=("bootstrap", "steady"))
    parser.add_argument("--external-scope", choices=("main", "restore", "both"))
    parser.add_argument("--caddy-config", type=Path)
    parser.add_argument("--caddy-compose", type=Path)
    parser.add_argument("--contract-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    try:
        policy = load_json(args.policy)
        main_compose = load_json(args.main_compose)
        restore_compose = load_json(args.restore_compose)
        init_compose = load_json(args.init_compose)
        restore_init_compose = load_json(args.restore_init_compose)
        bootstrap_compose = load_json(args.bootstrap_compose)
        restore_bootstrap_compose = load_json(args.restore_bootstrap_compose)
        caddy_mounts = load_json(args.caddy_mounts)
        errors.extend(validate_compose_contract(main_compose, restore_compose, policy))
        errors.extend(validate_init_overlays(init_compose, restore_init_compose))
        errors.extend(validate_bootstrap_overlays(bootstrap_compose, restore_bootstrap_compose))
        errors.extend(validate_caddy_mounts(caddy_mounts))
        try:
            errors.extend(validate_caddy_fragment(args.caddy_fragment.read_text(encoding="utf-8")))
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read Caddy fragment: {exc}")

        manifest: dict[str, Any] | None = None
        if args.manifest is not None:
            manifest = load_json(args.manifest)
            errors.extend(
                validate_manifest(
                    manifest,
                    policy,
                    args.repository_root.resolve(),
                    args.external_phase if args.check_external else None,
                    args.external_scope if args.check_external else None,
                )
            )
        elif not args.contract_only:
            errors.append("--manifest is required unless --contract-only is used")

        if args.check_external:
            if manifest is None:
                errors.append("--check-external requires --manifest")
            if args.external_phase is None:
                errors.append("--check-external requires --external-phase bootstrap or steady")
            if args.external_scope is None:
                errors.append("--check-external requires --external-scope main, restore or both")
            if args.caddy_config is None or args.caddy_compose is None:
                errors.append("--check-external requires --caddy-config and --caddy-compose")
            elif manifest is not None and args.external_phase is not None and args.external_scope is not None:
                errors.extend(
                    validate_external_inputs(
                        manifest,
                        policy,
                        args.database_template,
                        args.restore_database_template,
                        args.caddy_config,
                        args.caddy_compose,
                        args.external_phase,
                        args.external_scope,
                    )
                )
        else:
            if args.external_phase is not None:
                errors.append("--external-phase requires --check-external")
            if args.external_scope is not None:
                errors.append("--external-scope requires --check-external")
    except ValidationError as exc:
        errors.append(str(exc))

    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    mode = "contract" if args.contract_only and args.manifest is None else "release"
    print(f"[PASS] miaomu {mode} inputs validated")
    print("[INFO] registry, image architecture, Caddy syntax and runtime health require NUR-OPS-001 evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
