#!/usr/bin/env python3
"""Offline contract tests for the ShopXO nursery deployment inputs."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from typing import Any


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
DOCS = ROOT / "docs" / "operations"
VALIDATOR_PATH = DEPLOY / "validate_release_inputs.py"
RUNTIME_SANITIZER_PATH = DEPLOY / "docker" / "app" / "runtime-sanitize.sh"


def load_validator():
    spec = importlib.util.spec_from_file_location("miaomu_release_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release input validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


def load_json(name: str) -> dict[str, Any]:
    return VALIDATOR.load_json(DEPLOY / name)


def is_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and getattr(metadata, "st_file_attributes", 0) & marker)


def service_mounts(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in service.get("volumes", []):
        if isinstance(item, dict) and isinstance(item.get("target"), str):
            result[item["target"]] = item
    return result


def tmpfs_options(service: dict[str, Any], target: str) -> set[str] | None:
    for value in service.get("tmpfs", []):
        if not isinstance(value, str):
            continue
        path, separator, options = value.partition(":")
        if path == target and separator:
            return set(options.split(","))
    return None


def shell_commands(source: str) -> list[list[str]]:
    commands: list[list[str]] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            commands.append(shlex.split(line, posix=True))
        except ValueError:
            commands.append([line])
    return commands


def command_index(commands: list[list[str]], expected: list[str]) -> int:
    for index, command in enumerate(commands):
        if command == expected:
            return index
    return -1


def mysql_handoff_errors(
    main: dict[str, Any],
    restore: dict[str, Any],
    policy: dict[str, Any],
    wrapper_source: str | None,
) -> list[str]:
    errors: list[str] = []
    expected_caps = {"CHOWN", "SETGID", "SETUID"}
    expected_tmpfs = {
        "rw",
        "noexec",
        "nosuid",
        "nodev",
        "size=1m",
        "uid=0",
        "gid=0",
        "mode=0700",
    }

    for label, compose in (("main", main), ("restore", restore)):
        services = compose.get("services", {})
        db = services.get("db", {}) if isinstance(services, dict) else {}
        app = services.get("app", {}) if isinstance(services, dict) else {}
        if "user" in db:
            errors.append(f"{label}.db must start as root only through the wrapper")
        if db.get("group_add"):
            errors.append(f"{label}.db must not receive supplemental groups")
        if db.get("entrypoint") != ["/bin/sh", "/usr/local/bin/miaomu-mysql-entrypoint"]:
            errors.append(f"{label}.db wrapper entrypoint mismatch")
        if set(db.get("cap_add", [])) != expected_caps:
            errors.append(f"{label}.db bootstrap capabilities mismatch")
        if db.get("cap_drop") != ["ALL"]:
            errors.append(f"{label}.db must drop all other capabilities")
        if "no-new-privileges:true" not in db.get("security_opt", []):
            errors.append(f"{label}.db must enable no-new-privileges")
        if tmpfs_options(db, "/run/miaomu-db-secrets") != expected_tmpfs:
            errors.append(f"{label}.db private secret tmpfs mismatch")

        mounts = service_mounts(db)
        wrapper = mounts.get("/usr/local/bin/miaomu-mysql-entrypoint", {})
        if wrapper.get("source") != "./mysql-entrypoint.sh":
            errors.append(f"{label}.db wrapper source mismatch")
        if wrapper.get("read_only") is not True:
            errors.append(f"{label}.db wrapper must be read-only")
        if wrapper.get("bind", {}).get("create_host_path") is not False:
            errors.append(f"{label}.db wrapper bind must fail when source is missing")
        health_mount = mounts.get("/usr/local/bin/miaomu-mysql-healthcheck", {})
        if health_mount.get("source") != "./mysql-healthcheck.sh":
            errors.append(f"{label}.db healthcheck source mismatch")
        if health_mount.get("read_only") is not True:
            errors.append(f"{label}.db healthcheck script must be read-only")
        if set(db.get("secrets", [])) != {"mysql_app_password", "mysql_root_password"}:
            errors.append(f"{label}.db secret set mismatch")
        if app.get("secrets") != ["mysql_app_password"]:
            errors.append(f"{label}.app must receive only the application secret")
        if "/run/miaomu-db-secrets" in json.dumps(app, sort_keys=True):
            errors.append(f"{label}.app must not mount the database private tmpfs")

        environment = db.get("environment", {})
        if environment.get("MYSQL_PASSWORD_FILE") != "/run/secrets/mysql_app_password":
            errors.append(f"{label}.db application secret source mismatch")
        if environment.get("MYSQL_ROOT_PASSWORD_FILE") != "/run/secrets/mysql_root_password":
            errors.append(f"{label}.db root secret source mismatch")
        for forbidden in ("MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD"):
            if forbidden in environment:
                errors.append(f"{label}.db must not receive plaintext {forbidden}")
        health = db.get("healthcheck", {}).get("test", [])
        if health != ["CMD", "/bin/sh", "/usr/local/bin/miaomu-mysql-healthcheck", "steady"]:
            errors.append(f"{label}.db base healthcheck must require steady mode")

    identities = policy.get("service_identities", {})
    for key in ("external_files", "restore_external_files"):
        external = policy.get(key, {})
        if external.get("shared_required_uid") != 0:
            errors.append(f"{key} shared files must be owned by root")
        if external.get("shared_required_gid") != 10001:
            errors.append(f"{key} shared files must use group 10001")
        if external.get("shared_required_mode") != "0440":
            errors.append(f"{key} shared files must use mode 0440")
        if external.get("root_secret_required_uid") != 0:
            errors.append(f"{key} root secret owner mismatch")
        if external.get("root_secret_required_gid") != 0:
            errors.append(f"{key} root secret group must be root")
        if external.get("root_secret_required_mode") != "0400":
            errors.append(f"{key} root secret must use mode 0400")
    app_identity = identities.get("app", {})
    db_identity = identities.get("db", {})
    if app_identity != {
        "steady_uid": 10001,
        "steady_gid": 10001,
        "supplemental_groups": [],
    }:
        errors.append("policy app identity mismatch")
    if db_identity.get("bootstrap_uid") != 0:
        errors.append("policy db bootstrap UID must be root")
    if db_identity.get("steady_uid") != 999 or db_identity.get("steady_gid") != 999:
        errors.append("policy db steady identity must be 999:999")
    if db_identity.get("supplemental_groups") != []:
        errors.append("policy db must not have supplemental groups")
    if db_identity.get("steady_marker") != "/var/lib/mysql/.miaomu-steady":
        errors.append("policy db steady marker mismatch")
    if set(db_identity.get("bootstrap_capabilities", [])) != expected_caps:
        errors.append("policy db bootstrap capabilities mismatch")
    handoff = str(db_identity.get("secret_handoff", ""))
    for token in (
        "root-only",
        "tmpfs",
        "999:999",
        "0400",
        "0700",
        "steady marker",
        "unsets credentials",
        "gosu mysql",
    ):
        if token not in handoff:
            errors.append(f"policy secret handoff is missing {token}")

    if wrapper_source is None:
        errors.append("database bootstrap wrapper is missing")
        return errors

    commands = shell_commands(wrapper_source)
    if not wrapper_source.startswith("#!/bin/sh\n"):
        errors.append("wrapper must use /bin/sh")
    if command_index(commands, ["set", "-eu"]) < 0:
        errors.append("wrapper must fail on errors and unset variables")
    if "set -x" in wrapper_source or "set -o xtrace" in wrapper_source:
        errors.append("wrapper must not trace secret operations")
    if "$(" in wrapper_source or "`" in wrapper_source:
        errors.append("wrapper must not use command substitution")

    marker_declaration = wrapper_source.find(
        'readonly steady_marker="/var/lib/mysql/.miaomu-steady"'
    )
    marker_check = wrapper_source.find(
        'if gosu mysql test -f "${steady_marker}"; then'
    )
    unset_credentials = wrapper_source.find(
        "unset MYSQL_PASSWORD_FILE MYSQL_ROOT_PASSWORD_FILE MYSQL_PASSWORD MYSQL_ROOT_PASSWORD"
    )
    steady_exec = wrapper_source.find('exec gosu mysql "$@"')
    steady_branch_end = wrapper_source.find("\nfi\n", steady_exec)
    install_root = wrapper_source.find(
        'install -d -o 0 -g 0 -m 0700 "${private_dir}"'
    )
    copy_command = wrapper_source.find('cp -- "${source_path}" "${target_path}"')
    file_chmod = wrapper_source.find('chmod 0400 "${target_path}"')
    file_chown = wrapper_source.find('chown 999:999 "${target_path}"')
    app_copy = wrapper_source.find("copy_secret mysql_app_password")
    root_copy = wrapper_source.find("copy_secret mysql_root_password")
    directory_chown = wrapper_source.find('chown 999:999 "${private_dir}"')
    exec_mysql = wrapper_source.find(
        'exec gosu mysql /usr/local/bin/docker-entrypoint.sh "$@"'
    )
    required_indices = {
        "steady marker declaration": marker_declaration,
        "mysql-owned steady marker check": marker_check,
        "steady credential cleanup": unset_credentials,
        "direct steady mysql privilege drop": steady_exec,
        "steady branch end": steady_branch_end,
        "root-owned private directory": install_root,
        "secret copy": copy_command,
        "file mode": file_chmod,
        "file ownership": file_chown,
        "application secret copy": app_copy,
        "root secret copy": root_copy,
        "directory handoff": directory_chown,
        "bootstrap mysql privilege drop": exec_mysql,
    }
    for label, index in required_indices.items():
        if index < 0:
            errors.append(f"wrapper is missing {label}")
    if all(index >= 0 for index in (copy_command, file_chown, file_chmod)):
        if not copy_command < file_chmod < file_chown:
            errors.append("wrapper must copy, chmod, then chown each secret")
    if all(
        index >= 0
        for index in (
            marker_declaration,
            marker_check,
            unset_credentials,
            steady_exec,
            steady_branch_end,
            install_root,
        )
    ):
        if not (
            marker_declaration
            < marker_check
            < unset_credentials
            < steady_exec
            < steady_branch_end
            < install_root
        ):
            errors.append("steady marker branch must clear credentials before any bootstrap copy")
    if all(index >= 0 for index in (install_root, app_copy, root_copy, directory_chown, exec_mysql)):
        if not install_root < app_copy < root_copy < directory_chown < exec_mysql:
            errors.append("wrapper privilege handoff order is unsafe")
    if wrapper_source.count('exec gosu mysql "$@"') != 1:
        errors.append("wrapper must have one direct steady-state mysql exec")
    if wrapper_source.count("/var/lib/mysql/.miaomu-steady") != 1:
        errors.append("wrapper steady marker path must be declared exactly once")
    if re.search(r"(?m)^\s*(?:touch|install|cp|mv).*steady_marker", wrapper_source):
        errors.append("wrapper must never create or replace the steady marker")

    required_fragments = (
        '[ ! -f "${source_path}" ]',
        '[ -L "${source_path}" ]',
        '[ ! -s "${source_path}" ]',
        'export MYSQL_PASSWORD_FILE="${private_dir}/mysql_app_password"',
        'export MYSQL_ROOT_PASSWORD_FILE="${private_dir}/mysql_root_password"',
    )
    for fragment in required_fragments:
        if fragment not in wrapper_source:
            errors.append(f"wrapper is missing guarded fragment: {fragment}")

    banned_commands = {"cat", "tee", "env", "printenv", "base64", "xxd", "od", "hexdump"}
    for command in commands:
        if command and command[0] in banned_commands:
            errors.append(f"wrapper uses forbidden output command: {command[0]}")
    return errors


def mysql_healthcheck_errors(source: str) -> list[str]:
    errors: list[str] = []
    required = (
        "set -eu",
        'mode="${1:-}"',
        '"${mode}" != "bootstrap"',
        '"${mode}" != "steady"',
        "gosu mysql mysqladmin ping --protocol=socket --silent >/dev/null 2>&1",
        'if [ "${mode}" = "steady" ]; then',
        "gosu mysql test -f /var/lib/mysql/.miaomu-steady",
    )
    for fragment in required:
        if fragment not in source:
            errors.append(f"MySQL healthcheck is missing {fragment}")
    for forbidden in (
        "MYSQL_PASSWORD",
        "MYSQL_ROOT_PASSWORD",
        "/run/secrets",
        "/run/miaomu-db-secrets",
    ):
        if forbidden in source:
            errors.append(f"MySQL healthcheck must not access credentials: {forbidden}")
    return errors


def caddy_errors(source: str) -> list[str]:
    errors = list(VALIDATOR.validate_caddy_fragment(source))
    if "http://127.0.0.1:88 {" not in source:
        errors.append("Caddy listener must be loopback HTTP 88")
    for forbidden in ("38.12.21.18:88", "0.0.0.0:88", "PHP_VALUE", "PHP_ADMIN_VALUE"):
        if forbidden in source:
            errors.append(f"Caddy fragment contains forbidden token {forbidden}")
    if source.count("php_fastcgi unix//run/miaomu-fpm/php-fpm.sock") != 4:
        errors.append("Caddy fragment must use the fixed Unix socket in four handlers")
    for entrypoint in ("index", "admin", "api"):
        matcher = rf"(?m)^\s*handle\s+/{entrypoint}\.php\s+\{{\s*$"
        if re.search(matcher, source) is None:
            errors.append(f"Caddy literal /{entrypoint}.php handler is missing")
    if re.search(r"(?m)^\s*handle\s+[^\s{]*\.php[^\s{]+\s+\{\s*$", source):
        errors.append("Caddy PHP handlers must not use suffixes or wildcards")
    allowed_scripts = {
        "/var/www/html/public/index.php",
        "/var/www/html/public/admin.php",
        "/var/www/html/public/api.php",
    }
    scripts = set(re.findall(r"env SCRIPT_FILENAME ([^\s]+)", source))
    if scripts != allowed_scripts:
        errors.append("Caddy SCRIPT_FILENAME values must be the three literal entrypoints")
    required_denials = {
        "@download": r"(?m)^\s*@download\s+path_regexp\s+download\s+",
        "@sensitiveEntry": r"(?m)^\s*@sensitiveEntry\s+path_regexp\s+",
        "@hidden": r"(?m)^\s*@hidden\s+path_regexp\s+",
        "@sensitivePath": r"(?m)^\s*@sensitivePath\s+path_regexp\s+sensitivePath\s+",
        "@aceDemo": r"(?m)^\s*@aceDemo\s+path_regexp\s+",
        "@scriptLike": r"(?m)^\s*@scriptLike\s+path_regexp\s+",
    }
    static_index = source.find("@static file")
    file_server_index = source.find("file_server")
    if static_index < 0 or file_server_index < 0:
        errors.append("Caddy static file handler is missing")
    for marker, declaration in required_denials.items():
        index = source.find(marker)
        if index < 0:
            errors.append(f"Caddy denial {marker} is missing")
        elif static_index >= 0 and index > static_index:
            errors.append(f"Caddy denial {marker} must precede static handling")
        elif file_server_index >= 0 and index > file_server_index:
            errors.append(f"Caddy denial {marker} must precede file_server")
        if re.search(declaration, source) is None:
            errors.append(f"Caddy denial matcher {marker} is missing")
        if f"respond {marker} 404" not in source:
            errors.append(f"Caddy denial {marker} must return 404")
    if "rewrite * /index.php" not in source:
        errors.append("Caddy fallback rewrite is missing")
    return errors


def fpm_errors(pool_source: str, guard_source: str) -> list[str]:
    errors: list[str] = []
    compact = re.sub(r"\s+", "", pool_source)
    required_pool = (
        "user=10001",
        "group=10001",
        "listen=/run/miaomu-fpm/php-fpm.sock",
        "listen.owner=10001",
        "listen.group=10001",
        "listen.mode=0660",
        "clear_env=yes",
        "security.limit_extensions=.php",
        "php_admin_value[auto_prepend_file]=/usr/local/lib/miaomu/fpm-entry-guard.php",
    )
    for fragment in required_pool:
        if fragment not in compact:
            errors.append(f"FPM pool is missing {fragment}")
    if re.search(r"(?m)^\s*listen\s*=\s*(?:[0-9.]+:|\[)", pool_source):
        errors.append("FPM must not listen on TCP")
    if re.search(r"(?m)^\s*listen\.acl_(?:users|groups)\s*=", pool_source):
        errors.append("FPM socket ACLs must remain unset")

    allowed = {
        "/var/www/html/public/index.php",
        "/var/www/html/public/admin.php",
        "/var/www/html/public/api.php",
    }
    guard_paths = set(re.findall(r"['\"](/var/www/html/public/[^'\"]+\.php)['\"]", guard_source))
    if guard_paths != allowed:
        errors.append("FPM guard entrypoint allow-list mismatch")
    for fragment in (
        "PHP_SAPI",
        "'fpm-fcgi'",
        "$_SERVER['SCRIPT_FILENAME']",
        "'PATH_INFO'",
        "realpath($scriptFilename)",
    ):
        if fragment not in guard_source:
            errors.append(f"FPM guard is missing {fragment}")
    for forbidden in ("PHP_VALUE", "PHP_ADMIN_VALUE", "HTTP_", "$_GET", "$_POST"):
        if forbidden in guard_source:
            errors.append(f"FPM guard trusts forbidden request data {forbidden}")
    return errors


def database_template_errors(source: str, database: str, username: str) -> list[str]:
    errors: list[str] = []
    required = (
        "/run/secrets/mysql_app_password",
        "lstat($secretPath)",
        "is_file($secretPath)",
        "is_link($secretPath)",
        "is_readable($secretPath)",
        "['uid']",
        "['gid']",
        "0440",
        "file_get_contents($secretPath)",
        "$databaseCredential = @file_get_contents($secretPath)",
        "rtrim($databaseCredential",
        "str_contains($databaseCredential, \"\\0\")",
        "'hostname'        => 'db'",
        f"'database'        => '{database}'",
        f"'username'        => '{username}'",
    )
    for fragment in required:
        if fragment not in source:
            errors.append(f"database template is missing {fragment}")
    if "database credential is unavailable" not in source:
        errors.append("database template must use a generic credential error")
    if re.search(
        r"\(\s*['\"]pass['\"]\s*\.\s*['\"]word['\"]\s*\)\s*=>\s*\$databaseCredential",
        source,
    ) is None:
        errors.append("database template must assign the file credential to the split password key")
    if re.search(
        r"(?i)(?:['\"]password['\"]|\(\s*['\"]pass['\"]\s*\.\s*['\"]word['\"]\s*\))"
        r"\s*=>\s*['\"][^'\"]+['\"]",
        source,
    ) or re.search(r"\$databaseCredential\s*=\s*['\"][^'\"]+['\"]", source):
        errors.append("database template contains a literal password")
    for forbidden in ("$password", "getenv(", "$_ENV", "$_SERVER"):
        if forbidden in source:
            errors.append(f"database template uses a forbidden credential source {forbidden}")
    if source.count("file_get_contents($secretPath)") != 1:
        errors.append("database template must read the credential file exactly once")
    return errors


def event_bootstrap_errors(source: str) -> list[str]:
    errors: list[str] = []
    required = (
        "use app\\service\\PluginsAdminService;",
        "use app\\plugins\\nursery\\service\\CatalogMigration;",
        "PHP_SAPI !== 'cli'",
        "event_bootstrap_metadata_invalid",
        "($eventStat['uid'] ?? -1) !== 0",
        "($eventStat['gid'] ?? -1) !== 10001",
        "!== 0660",
        "PluginsAdminService::PluginsInstall",
        "PluginsAdminService::PluginsStatusUpdate(['id'=>'nursery', 'state'=>0])",
        "PluginsAdminService::PluginsStatusUpdate(['id'=>'nursery', 'state'=>1])",
        "CatalogMigration::Run('existing', $actor, $runId)",
        "array_diff($enabled, ['nursery'])",
        "$enabled !== ['nursery']",
        "$events['listen'] === $config['hook']",
        "preg_match('/^[A-Za-z0-9._-]{3,80}$/D'",
        "preg_match('/^[A-Za-z0-9._-]{8,120}$/D'",
        '$safeEventStub = "<?php\\nreturn [];\\n";',
        "file_put_contents($eventPath, $safeEventStub, LOCK_EX)",
        "$written !== strlen($safeEventStub)",
    )
    for fragment in required:
        if fragment not in source:
            errors.append(f"nursery bootstrap is missing {fragment}")
    if source.count("file_put_contents(") != 1:
        errors.append("nursery bootstrap may write only the fixed safe event stub")
    stub_write = source.find("file_put_contents($eventPath, $safeEventStub, LOCK_EX)")
    framework_start = source.find("require $root.'/public/core.php'")
    official_install = source.find("PluginsAdminService::PluginsInstall")
    if not (0 <= stub_write < framework_start < official_install):
        errors.append("safe event stub must be written before the official bootstrap starts")
    for forbidden in ("fopen($eventPath", "unlink($eventPath", "rename($eventPath"):
        if forbidden in source:
            errors.append("nursery bootstrap must not hand-write the generated event")
    return errors


def readiness_errors(source: str) -> list[str]:
    errors: list[str] = []
    required = (
        "$eventPath = MIAOMU_ROOT.'/app/event.php'",
        "$eventStat = @lstat($eventPath)",
        "!is_writable($eventPath)",
        "($eventStat['uid'] ?? -1) === 0",
        "($eventStat['gid'] ?? -1) === 10001",
        "(($eventStat['mode'] ?? 0) & 0777) === 0440",
        "array_keys($events) === ['listen']",
        "$events['listen'] === $pluginConfig['hook']",
        "plugins_nursery_catalog_manifest",
        "'SELECT plugins FROM '.$prefix.'plugins WHERE is_enable = 1 ORDER BY plugins'",
        "$enabledPlugins === ['nursery']",
        "generated_event_metadata",
        "nursery_event_bindings",
        "enabled_plugin_set",
        "$connectionString = sprintf(",
        "new PDO(",
        "$connectionString,",
    )
    for fragment in required:
        if fragment not in source:
            errors.append(f"environment readiness is missing {fragment}")
    if "$dsn" in source:
        errors.append("environment readiness must use the scanner-safe connection string name")
    return errors


def runtime_sanitize_errors(entrypoint: str, sanitizer: str, dockerfile: str) -> list[str]:
    errors: list[str] = []
    sanitizer_call = '/usr/local/bin/miaomu-runtime-sanitize "${MIAOMU_ENV:-}"'
    php_fpm_branch = 'if [ "${1:-}" = "php-fpm" ]; then\n    managed_start=true'
    initializer_branch = (
        'elif [ "${1:-}" = "php" ] \\\n'
        '    && [ "${2:-}" = "/usr/local/lib/miaomu/nursery-bootstrap.php" ] \\\n'
        '    && [ "${3:-}" = "initialize" ]; then\n'
        '    managed_start=true'
    )
    managed_guard = 'if [ "$managed_start" = "true" ]; then'
    readiness = "php /usr/local/lib/miaomu/environment_check.php --startup"
    for fragment, label in (
        ("managed_start=false", "default unmanaged state"),
        (php_fpm_branch, "php-fpm managed entry"),
        (initializer_branch, "exact nursery initializer entry"),
        (managed_guard, "managed-entry guard"),
        (sanitizer_call, "runtime sanitizer invocation"),
    ):
        if fragment not in entrypoint:
            errors.append(f"entrypoint is missing {label}")
    if entrypoint.count(sanitizer_call) != 1:
        errors.append("entrypoint must invoke the runtime sanitizer exactly once")
    if entrypoint.count("managed_start=true") != 2 or entrypoint.count("managed_start=false") != 1:
        errors.append("entrypoint must authorize exactly php-fpm and nursery initialize")
    sanitizer_index = entrypoint.find(sanitizer_call)
    guard_index = entrypoint.find(managed_guard)
    readiness_index = entrypoint.find(readiness)
    final_exec_index = entrypoint.find('exec "$@"')
    if not (
        guard_index >= 0
        and sanitizer_index >= 0
        and readiness_index >= 0
        and final_exec_index >= 0
        and guard_index < sanitizer_index < readiness_index < final_exec_index
    ):
        errors.append("runtime sanitization must precede framework readiness and command exec")

    required_paths = (
        "cache",
        "session",
        "temp",
        "admin/temp",
        "index/temp",
        "api/temp",
        "data/config_data",
    )
    path_block = re.search(r"for relative_path in \\\n(?P<body>.*?)\ndo\n", sanitizer, re.DOTALL)
    if path_block is None:
        errors.append("runtime sanitizer fixed path list is missing")
    else:
        configured_paths = tuple(
            line.strip().removesuffix(" \\")
            for line in path_block.group("body").splitlines()
            if line.strip()
        )
        if configured_paths != required_paths:
            errors.append("runtime sanitizer path allow-list mismatch")

    for fragment, label in (
        ('[ "$#" -eq 1 ]', "single fixed mode argument"),
        ('production|restore) ;;', "production and restore mode allow-list"),
        ('runtime_root="/var/www/html/runtime"', "fixed runtime root"),
        ('[ -d "$runtime_root" ]', "runtime directory check"),
        ('[ ! -L "$runtime_root" ]', "runtime root symlink rejection"),
        ('[ "$(readlink -f "$runtime_root")" = "$runtime_root" ]', "canonical runtime root check"),
        ('find "$runtime_root" -xdev -type l -print -quit', "nested symlink rejection"),
        ('if [ "$mode" = "restore" ]; then', "restore-only full cleanup"),
        (
            'find "$runtime_root" -xdev -mindepth 1 -delete',
            "restore runtime emptying",
        ),
        ('target="$runtime_root/$relative_path"', "fixed-root target construction"),
        ('"$runtime_root"/*) ;;', "target containment check"),
        ('[ -d "$target" ]', "target directory check"),
        ('find "$target" -xdev -mindepth 1 -delete', "bounded target cleanup"),
        ('mkdir -p "$target"', "known directory recreation"),
    ):
        if fragment not in sanitizer:
            errors.append(f"runtime sanitizer is missing {label}")

    restore_guard = sanitizer.find('if [ "$mode" = "restore" ]; then')
    restore_cleanup = sanitizer.find('find "$runtime_root" -xdev -mindepth 1 -delete')
    restore_guard_end = sanitizer.find("\nfi\n", restore_cleanup)
    if not (
        restore_guard >= 0
        and restore_cleanup >= 0
        and restore_guard_end >= 0
        and restore_guard < restore_cleanup < restore_guard_end
    ):
        errors.append("full runtime cleanup must remain inside the restore-only branch")

    for forbidden in ("MIAOMU_RUNTIME_ROOT", '${2:-}', "$2", "getopts", "eval "):
        if forbidden in sanitizer:
            errors.append(f"runtime sanitizer accepts a variable cleanup path via {forbidden}")
    for command in shell_commands(sanitizer):
        if not command:
            continue
        if command[0] == "rm":
            errors.append("runtime sanitizer must not use broad rm cleanup")
        if command[0] == "find" and "-xdev" not in command:
            errors.append("every runtime find must stay on the runtime filesystem")

    copy_line = (
        "COPY --chown=0:0 deploy/docker/app/runtime-sanitize.sh "
        "/usr/local/bin/miaomu-runtime-sanitize"
    )
    if copy_line not in dockerfile:
        errors.append("runtime sanitizer must be a fixed root-owned image artifact")
    chmod_block = re.search(r"chmod 0555 \\\n(?P<body>.*?)\n\s*&& chmod 0444", dockerfile, re.DOTALL)
    if chmod_block is None or "/usr/local/bin/miaomu-runtime-sanitize" not in chmod_block.group("body"):
        errors.append("runtime sanitizer image artifact must be mode 0555")
    return errors


class RequiredArtifactTests(unittest.TestCase):
    def test_required_files_are_regular_and_not_reparse_points(self) -> None:
        required = [
            DEPLOY / "compose.yaml",
            DEPLOY / "compose.restore.yaml",
            DEPLOY / "compose.init.yaml",
            DEPLOY / "compose.restore.init.yaml",
            DEPLOY / "compose.bootstrap.yaml",
            DEPLOY / "compose.restore.bootstrap.yaml",
            DEPLOY / "mysql-entrypoint.sh",
            DEPLOY / "mysql-healthcheck.sh",
            DEPLOY / "Caddyfile.miaomu",
            DEPLOY / "caddy-mounts.json",
            DEPLOY / "stack-policy.json",
            DEPLOY / "validate_release_inputs.py",
            DEPLOY / "release-manifest.example.json",
            DEPLOY / "docker" / "app" / "Dockerfile",
            DEPLOY / "docker" / "app" / "Dockerfile.dockerignore",
            DEPLOY / "docker" / "app" / "docker-entrypoint.sh",
            RUNTIME_SANITIZER_PATH,
            DEPLOY / "docker" / "app" / "php.ini",
            DEPLOY / "docker" / "app" / "www.conf",
            DEPLOY / "docker" / "app" / "fpm-entry-guard.php",
            DEPLOY / "docker" / "app" / "nursery-bootstrap.php",
            DEPLOY / "config" / "database.php.example",
            DEPLOY / "config" / "database.restore.php.example",
            ROOT / "tests" / "ops" / "environment_check.php",
            DOCS / "DEPLOYMENT.md",
            DOCS / "LOCAL_STACK.md",
            DOCS / "BACKUP_RESTORE.md",
            DOCS / "PERFORMANCE_BASELINE.md",
        ]
        for path in required:
            with self.subTest(path=path.relative_to(ROOT)):
                if not path.is_file():
                    self.fail(f"required artifact is missing: {path}")
                self.assertFalse(path.is_symlink(), f"artifact must not be a symlink: {path}")
                self.assertFalse(is_reparse_point(path), f"artifact must not traverse a reparse point: {path}")

    def test_json_loader_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"services": {}, "services": {}}', encoding="utf-8")
            with self.assertRaises(VALIDATOR.ValidationError):
                VALIDATOR.load_json(path)


class ComposeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = load_json("compose.yaml")
        self.restore = load_json("compose.restore.yaml")
        self.init = load_json("compose.init.yaml")
        self.restore_init = load_json("compose.restore.init.yaml")
        self.bootstrap = load_json("compose.bootstrap.yaml")
        self.restore_bootstrap = load_json("compose.restore.bootstrap.yaml")
        self.policy = load_json("stack-policy.json")

    def test_validator_accepts_actual_compose_contract(self) -> None:
        self.assertEqual([], VALIDATOR.validate_compose_contract(self.main, self.restore, self.policy))
        self.assertEqual([], VALIDATOR.validate_init_overlays(self.init, self.restore_init))
        self.assertEqual(
            [],
            VALIDATOR.validate_bootstrap_overlays(self.bootstrap, self.restore_bootstrap),
        )

    def test_topology_is_internal_bounded_and_immutable(self) -> None:
        digest_reference = re.compile(r"^[^\s:]+(?::[^\s@]+)?@sha256:[0-9a-f]{64}$")
        for label, compose in (("main", self.main), ("restore", self.restore)):
            self.assertEqual({"app", "db"}, set(compose["services"]), label)
            self.assertTrue(compose["networks"]["backend"]["internal"], label)
            for service_name, service in compose["services"].items():
                with self.subTest(stack=label, service=service_name):
                    self.assertNotIn("ports", service)
                    self.assertNotIn("/var/run/docker.sock", json.dumps(service, sort_keys=True))
                    self.assertTrue(service["read_only"])
                    self.assertEqual(["ALL"], service["cap_drop"])
                    self.assertEqual("false", service["labels"]["com.centurylinklabs.watchtower.enable"])
                    self.assertGreater(service["pids_limit"], 0)
                    self.assertTrue(service["cpus"])
                    self.assertRegex(service["mem_limit"], r"^[0-9]+[mg]$")
                    self.assertEqual("json-file", service["logging"]["driver"])
            self.assertRegex(compose["services"]["db"]["image"], digest_reference)
            self.assertNotIn(":latest", json.dumps(compose, sort_keys=True).lower())

        main_app = self.main["services"]["app"]
        self.assertEqual("..", main_app["build"]["context"])
        self.assertEqual("deploy/docker/app/Dockerfile", main_app["build"]["dockerfile"])
        self.assertEqual("runtime", main_app["build"]["target"])
        self.assertIn("MIAOMU_RELEASE_SHA", main_app["build"]["args"])
        self.assertEqual("never", main_app["pull_policy"])

    def test_main_and_restore_resources_are_isolated(self) -> None:
        self.assertNotEqual(
            self.main["networks"]["backend"]["name"],
            self.restore["networks"]["backend"]["name"],
        )
        for key in ("runtime", "uploads", "downloads", "fpm_socket", "db_data"):
            with self.subTest(volume=key):
                self.assertNotEqual(
                    self.main["volumes"][key]["name"],
                    self.restore["volumes"][key]["name"],
                )
        for secret in ("mysql_app_password", "mysql_root_password"):
            self.assertTrue(self.main["secrets"][secret]["file"].startswith("/etc/miaomu/"))
            self.assertTrue(self.restore["secrets"][secret]["file"].startswith("/etc/miaomu-restore/"))
            self.assertNotEqual(
                self.main["secrets"][secret]["file"],
                self.restore["secrets"][secret]["file"],
            )

    def test_top_level_named_volume_definitions_are_plain_and_locked(self) -> None:
        expected_names = {
            "main": {
                "runtime": "miaomu_runtime",
                "uploads": "miaomu_uploads",
                "downloads": "miaomu_downloads",
                "fpm_socket": "miaomu_fpm_socket",
                "db_data": "miaomu_db_data",
            },
            "restore": {
                "runtime": "miaomu_restore_runtime",
                "uploads": "miaomu_restore_uploads",
                "downloads": "miaomu_restore_downloads",
                "fpm_socket": "miaomu_restore_fpm_socket",
                "db_data": "miaomu_restore_db_data",
            },
        }
        for stack_name, original in (("main", self.main), ("restore", self.restore)):
            for volume_key, locked_name in expected_names[stack_name].items():
                with self.subTest(stack=stack_name, volume=volume_key, contract="positive"):
                    self.assertEqual(
                        {"name": locked_name},
                        original["volumes"][volume_key],
                    )

                mutations: list[tuple[str, dict[str, Any]]] = []
                wrong_name = copy.deepcopy(original)
                wrong_name["volumes"][volume_key]["name"] = f"{locked_name}_other"
                mutations.append(("changed locked name", wrong_name))

                bind_backed = copy.deepcopy(original)
                bind_backed["volumes"][volume_key].update(
                    {
                        "driver": "local",
                        "driver_opts": {
                            "type": "none",
                            "o": "bind",
                            "device": f"/tmp/{locked_name}",
                        },
                    }
                )
                mutations.append(("bind-backed local driver", bind_backed))

                external = copy.deepcopy(original)
                external["volumes"][volume_key]["external"] = True
                mutations.append(("external volume", external))

                extra_key = copy.deepcopy(original)
                extra_key["volumes"][volume_key]["labels"] = {
                    "com.example.unapproved": "true"
                }
                mutations.append(("extra volume key", extra_key))

                for mutation_name, mutated_stack in mutations:
                    main = mutated_stack if stack_name == "main" else self.main
                    restore = mutated_stack if stack_name == "restore" else self.restore
                    with self.subTest(
                        stack=stack_name,
                        volume=volume_key,
                        mutation=mutation_name,
                    ):
                        self.assertTrue(
                            VALIDATOR.validate_compose_contract(main, restore, self.policy),
                            "unsafe top-level volume mutation unexpectedly passed",
                        )

    def test_every_service_mount_has_the_locked_type_and_access_mode(self) -> None:
        expected_mounts = {
            "app": {
                "/var/www/html/config/database.php": "bind",
                "/var/www/html/app/event.php": "bind",
                "/var/www/html/runtime": "volume",
                "/var/www/html/public/static/upload": "volume",
                "/var/www/html/public/download": "volume",
                "/run/miaomu-fpm": "volume",
            },
            "db": {
                "/usr/local/bin/miaomu-mysql-entrypoint": "bind",
                "/usr/local/bin/miaomu-mysql-healthcheck": "bind",
                "/var/lib/mysql": "volume",
            },
        }
        for stack_name, compose in (("main", self.main), ("restore", self.restore)):
            for service_name, expected in expected_mounts.items():
                mounts = service_mounts(compose["services"][service_name])
                self.assertEqual(set(expected), set(mounts), f"{stack_name}.{service_name}")
                for target, mount_type in expected.items():
                    with self.subTest(stack=stack_name, service=service_name, target=target):
                        mount = mounts[target]
                        self.assertEqual(mount_type, mount.get("type"))
                        if mount_type == "bind":
                            self.assertTrue(mount.get("read_only"))
                            self.assertEqual(
                                {"create_host_path": False},
                                mount.get("bind"),
                            )
                        else:
                            self.assertFalse(mount.get("read_only", False))
                            self.assertNotIn("bind", mount)

    def test_mount_type_and_access_mutations_fail_closed(self) -> None:
        for stack_name, original in (("main", self.main), ("restore", self.restore)):
            for service_name in ("app", "db"):
                mounts = service_mounts(original["services"][service_name])
                for target, original_mount in mounts.items():
                    mount_type = original_mount.get("type")
                    mutations: list[tuple[str, dict[str, Any]]] = []
                    changed_type = copy.deepcopy(original)
                    changed_mount = service_mounts(changed_type["services"][service_name])[target]
                    changed_mount["type"] = "volume" if mount_type == "bind" else "bind"
                    mutations.append(("changed type", changed_type))

                    if mount_type == "bind":
                        writable = copy.deepcopy(original)
                        service_mounts(writable["services"][service_name])[target]["read_only"] = False
                        mutations.append(("writable bind", writable))

                        host_path_creation = copy.deepcopy(original)
                        service_mounts(host_path_creation["services"][service_name])[target]["bind"] = {
                            "create_host_path": True
                        }
                        mutations.append(("bind can create host path", host_path_creation))
                    else:
                        read_only = copy.deepcopy(original)
                        service_mounts(read_only["services"][service_name])[target]["read_only"] = True
                        mutations.append(("read-only named volume", read_only))

                    for mutation_name, mutated_stack in mutations:
                        main = mutated_stack if stack_name == "main" else self.main
                        restore = mutated_stack if stack_name == "restore" else self.restore
                        with self.subTest(
                            stack=stack_name,
                            service=service_name,
                            target=target,
                            mutation=mutation_name,
                        ):
                            self.assertTrue(
                                VALIDATOR.validate_compose_contract(main, restore, self.policy),
                                "unsafe mount mutation unexpectedly passed",
                            )

        for stack_name, original in (("main", self.main), ("restore", self.restore)):
            relative = copy.deepcopy(original)
            service_mounts(relative["services"]["app"])[
                "/var/www/html/config/database.php"
            ]["source"] = "./database.php"
            main = relative if stack_name == "main" else self.main
            restore = relative if stack_name == "restore" else self.restore
            with self.subTest(stack=stack_name, mutation="relative external bind"):
                self.assertTrue(
                    VALIDATOR.validate_compose_contract(main, restore, self.policy),
                    "relative external bind unexpectedly passed",
                )

    def test_compose_security_mutations_fail_closed(self) -> None:
        mutations: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []

        main = copy.deepcopy(self.main)
        main["services"]["web"] = copy.deepcopy(main["services"]["app"])
        mutations.append(("extra service", main, self.restore, self.policy))

        for service_name in ("app", "db"):
            main = copy.deepcopy(self.main)
            main["services"][service_name]["ports"] = ["9000:9000"]
            mutations.append((f"{service_name} published port", main, self.restore, self.policy))

        main = copy.deepcopy(self.main)
        main["networks"]["backend"]["internal"] = False
        mutations.append(("external backend", main, self.restore, self.policy))

        main = copy.deepcopy(self.main)
        main["services"]["app"]["user"] = "0:0"
        mutations.append(("root app", main, self.restore, self.policy))

        for service_name in ("app", "db"):
            main = copy.deepcopy(self.main)
            main["services"][service_name]["read_only"] = False
            mutations.append((f"{service_name} writable root", main, self.restore, self.policy))

        main = copy.deepcopy(self.main)
        main["services"]["app"]["volumes"].append(
            {
                "type": "bind",
                "source": "/var/run/docker.sock",
                "target": "/var/run/docker.sock",
                "read_only": False,
            }
        )
        mutations.append(("Docker socket", main, self.restore, self.policy))

        main = copy.deepcopy(self.main)
        main["services"]["db"]["labels"]["com.centurylinklabs.watchtower.enable"] = "true"
        mutations.append(("Watchtower enabled", main, self.restore, self.policy))

        restore = copy.deepcopy(self.restore)
        restore["volumes"]["fpm_socket"]["name"] = self.main["volumes"]["fpm_socket"]["name"]
        mutations.append(("shared restore socket", self.main, restore, self.policy))

        policy = copy.deepcopy(self.policy)
        policy["fpm_socket"]["mode"] = "0666"
        mutations.append(("world-writable FPM socket", self.main, self.restore, policy))

        main = copy.deepcopy(self.main)
        service_mounts(main["services"]["app"])["/var/www/html/app/event.php"]["read_only"] = False
        mutations.append(("writable steady event", main, self.restore, self.policy))

        restore = copy.deepcopy(self.restore)
        service_mounts(restore["services"]["app"])["/var/www/html/app/event.php"]["source"] = (
            "/etc/miaomu/generated/event.php"
        )
        mutations.append(("restore reuses main event", self.main, restore, self.policy))

        policy = copy.deepcopy(self.policy)
        policy["event_generation"]["allowed_enabled_plugins"].append("other")
        mutations.append(("additional enabled plugin", self.main, self.restore, policy))

        main = copy.deepcopy(self.main)
        main["services"]["db"]["healthcheck"]["test"][-1] = "bootstrap"
        mutations.append(("base database accepts bootstrap health", main, self.restore, self.policy))

        for name, main, restore, policy in mutations:
            with self.subTest(mutation=name):
                errors = VALIDATOR.validate_compose_contract(main, restore, policy)
                self.assertTrue(errors, f"unsafe Compose mutation passed: {name}")

    def test_init_overlay_mutations_fail_closed(self) -> None:
        mutations: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

        init = copy.deepcopy(self.init)
        init["services"]["db"] = {}
        mutations.append(("init modifies db", init, self.restore_init))

        init = copy.deepcopy(self.init)
        init["services"]["app"]["restart"] = "unless-stopped"
        mutations.append(("init can restart", init, self.restore_init))

        init = copy.deepcopy(self.init)
        init["services"]["app"]["volumes"][0]["read_only"] = True
        mutations.append(("init event is read-only", init, self.restore_init))

        init = copy.deepcopy(self.init)
        init["services"]["app"]["volumes"][0]["target"] = "/var/www/html/app/other.php"
        mutations.append(("init event target changed", init, self.restore_init))

        restore_init = copy.deepcopy(self.restore_init)
        restore_init["services"]["app"]["volumes"][0]["source"] = (
            "/etc/miaomu/generated/event.php"
        )
        mutations.append(("restore init reuses main event", self.init, restore_init))

        for name, init, restore_init in mutations:
            with self.subTest(mutation=name):
                self.assertTrue(
                    VALIDATOR.validate_init_overlays(init, restore_init),
                    f"unsafe init overlay mutation passed: {name}",
                )

    def test_database_bootstrap_overlay_mutations_fail_closed(self) -> None:
        mutations: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

        bootstrap = copy.deepcopy(self.bootstrap)
        bootstrap["services"]["app"] = {}
        mutations.append(("bootstrap modifies app", bootstrap, self.restore_bootstrap))

        bootstrap = copy.deepcopy(self.bootstrap)
        bootstrap["services"]["db"]["restart"] = "unless-stopped"
        mutations.append(("bootstrap can restart", bootstrap, self.restore_bootstrap))

        bootstrap = copy.deepcopy(self.bootstrap)
        bootstrap["services"]["db"]["healthcheck"]["test"][-1] = "steady"
        mutations.append(("bootstrap requires steady marker", bootstrap, self.restore_bootstrap))

        restore_bootstrap = copy.deepcopy(self.restore_bootstrap)
        restore_bootstrap["name"] = "miaomu"
        mutations.append(("restore bootstrap reuses main project", self.bootstrap, restore_bootstrap))

        for name, bootstrap, restore_bootstrap in mutations:
            with self.subTest(mutation=name):
                self.assertTrue(
                    VALIDATOR.validate_bootstrap_overlays(bootstrap, restore_bootstrap),
                    f"unsafe bootstrap overlay mutation passed: {name}",
                )

    def test_contract_validator_command_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(VALIDATOR_PATH), "--contract-only"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("[PASS] miaomu contract inputs validated", result.stdout)
        self.assertIn("require NUR-OPS-001 evidence", result.stdout)


class ReleaseInputContractTests(unittest.TestCase):
    def test_main_restore_templates_and_generated_events_are_independent(self) -> None:
        policy = load_json("stack-policy.json")
        manifest_example = load_json("release-manifest.example.json")
        self.assertNotEqual(
            policy["external_files"]["database_config"],
            policy["restore_external_files"]["database_config"],
        )
        self.assertNotEqual(
            policy["external_files"]["generated_event"],
            policy["restore_external_files"]["generated_event"],
        )
        for key in ("database_config_sha256", "restore_database_config_sha256"):
            self.assertIn(key, manifest_example)
        self.assertEqual({"main", "restore"}, set(manifest_example["generated_events"]))
        for stack_name in ("main", "restore"):
            self.assertEqual(
                {"state", "sha256"},
                set(manifest_example["generated_events"][stack_name]),
            )
        for legacy_key in (
            "generated_event_state",
            "generated_event_sha256",
            "restore_generated_event_sha256",
        ):
            self.assertNotIn(legacy_key, manifest_example)

    @staticmethod
    def valid_manifest(generated_events: dict[str, dict[str, Any]]) -> dict[str, Any]:
        policy = load_json("stack-policy.json")
        release_sha = "a" * 40
        digest = "b" * 64
        return {
            "schema_version": 2,
            "release_sha": release_sha,
            "target_platform": policy["target"]["platform"],
            "projects": {"main": "miaomu", "restore": "miaomu_restore"},
            "socket": {
                "main_volume": "miaomu_fpm_socket",
                "restore_volume": "miaomu_restore_fpm_socket",
                "path": "/run/miaomu-fpm/php-fpm.sock",
                "gid": 10001,
                "mode": "0660",
            },
            "database_config_sha256": digest,
            "restore_database_config_sha256": digest,
            "generated_events": generated_events,
            "images": {
                key: {
                    "reference": policy["images"][key]["reference"],
                    "platform_digest": digest,
                    "image_id": digest,
                }
                for key in ("php_base", "composer", "mysql")
            }
            | {
                "app": {
                    "reference": f"miaomu-app:{release_sha}",
                    "image_id": digest,
                }
            },
            "caddy": {
                "container": "jia-caddy",
                "version": "2.11.2",
                "config_sha256": digest,
                "compose_sha256": digest,
            },
        }

    def test_manifest_event_phase_is_scoped_per_stack(self) -> None:
        policy = load_json("stack-policy.json")
        generated = {"state": "generated", "sha256": "c" * 64}
        pending = {"state": "pending", "sha256": None}
        main_ready = self.valid_manifest(
            {"main": copy.deepcopy(generated), "restore": copy.deepcopy(pending)}
        )
        restore_ready = self.valid_manifest(
            {"main": copy.deepcopy(pending), "restore": copy.deepcopy(generated)}
        )
        both_ready = self.valid_manifest(
            {"main": copy.deepcopy(generated), "restore": copy.deepcopy(generated)}
        )
        both_pending = self.valid_manifest(
            {"main": copy.deepcopy(pending), "restore": copy.deepcopy(pending)}
        )

        with mock.patch.object(VALIDATOR, "git_state", return_value=("a" * 40, False)):
            self.assertEqual(
                [],
                VALIDATOR.validate_manifest(main_ready, policy, ROOT, "steady", "main"),
            )
            self.assertEqual(
                [],
                VALIDATOR.validate_manifest(restore_ready, policy, ROOT, "steady", "restore"),
            )
            self.assertEqual(
                [],
                VALIDATOR.validate_manifest(both_ready, policy, ROOT, "steady", "both"),
            )
            self.assertEqual(
                [],
                VALIDATOR.validate_manifest(both_pending, policy, ROOT, "bootstrap", "both"),
            )
            self.assertTrue(
                VALIDATOR.validate_manifest(main_ready, policy, ROOT, "steady", "restore")
            )
            self.assertTrue(
                VALIDATOR.validate_manifest(restore_ready, policy, ROOT, "steady", "main")
            )
            self.assertTrue(
                VALIDATOR.validate_manifest(main_ready, policy, ROOT, "steady", "both")
            )

            invalid_unselected = copy.deepcopy(main_ready)
            invalid_unselected["generated_events"]["restore"]["state"] = "unknown"
            self.assertTrue(
                VALIDATOR.validate_manifest(
                    invalid_unselected,
                    policy,
                    ROOT,
                    "steady",
                    "main",
                )
            )

    def test_external_validator_honors_main_restore_and_both_scope(self) -> None:
        main_template = DEPLOY / "config" / "database.php.example"
        restore_template = DEPLOY / "config" / "database.restore.php.example"
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            paths = {
                "main_config": temp / "main-database.php",
                "main_app_secret": temp / "main-app-secret",
                "main_root_secret": temp / "main-root-secret",
                "main_event": temp / "main-event.php",
                "restore_config": temp / "restore-database.php",
                "restore_app_secret": temp / "restore-app-secret",
                "restore_root_secret": temp / "restore-root-secret",
                "restore_event": temp / "restore-event.php",
                "caddy_config": temp / "Caddyfile",
                "caddy_compose": temp / "compose.yaml",
            }
            paths["main_config"].write_bytes(main_template.read_bytes())
            paths["restore_config"].write_bytes(restore_template.read_bytes())
            for key in ("main_app_secret", "main_root_secret", "restore_app_secret", "restore_root_secret"):
                paths[key].write_bytes(b"fixture-only-not-a-secret\n")
            paths["main_event"].write_text("<?php return ['listen'=>[]];\n", encoding="utf-8")
            paths["restore_event"].write_text("<?php return ['listen'=>['restore'=>[]]];\n", encoding="utf-8")
            paths["caddy_config"].write_text("fixture-caddy\n", encoding="utf-8")
            paths["caddy_compose"].write_text("fixture-compose\n", encoding="utf-8")

            policy = load_json("stack-policy.json")
            policy["external_files"].update(
                {
                    "database_config": str(paths["main_config"]),
                    "mysql_app_password": str(paths["main_app_secret"]),
                    "mysql_root_password": str(paths["main_root_secret"]),
                    "generated_event": str(paths["main_event"]),
                }
            )
            policy["restore_external_files"].update(
                {
                    "database_config": str(paths["restore_config"]),
                    "mysql_app_password": str(paths["restore_app_secret"]),
                    "mysql_root_password": str(paths["restore_root_secret"]),
                    "generated_event": str(paths["restore_event"]),
                }
            )
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = {
                "database_config_sha256": digest(main_template),
                "restore_database_config_sha256": digest(restore_template),
                "generated_events": {
                    "main": {
                        "state": "generated",
                        "sha256": digest(paths["main_event"]),
                    },
                    "restore": {
                        "state": "generated",
                        "sha256": digest(paths["restore_event"]),
                    },
                },
                "caddy": {
                    "config_sha256": digest(paths["caddy_config"]),
                    "compose_sha256": digest(paths["caddy_compose"]),
                },
            }
            with mock.patch.object(
                VALIDATOR,
                "validate_external_file_metadata",
                return_value=[],
            ) as metadata_check:
                errors = VALIDATOR.validate_external_inputs(
                    manifest,
                    policy,
                    main_template,
                    restore_template,
                    paths["caddy_config"],
                    paths["caddy_compose"],
                    "steady",
                    "both",
                )
                self.assertEqual([], errors)
                metadata_check.assert_any_call(
                    paths["main_root_secret"],
                    "main root database secret",
                    expected_gid=0,
                    expected_mode=0o400,
                )
                metadata_check.assert_any_call(
                    paths["restore_root_secret"],
                    "restore root database secret",
                    expected_gid=0,
                    expected_mode=0o400,
                )

                main_only = copy.deepcopy(manifest)
                main_only["generated_events"]["restore"] = {
                    "state": "pending",
                    "sha256": None,
                }
                paths["restore_config"].write_text("wrong restore config\n", encoding="utf-8")
                paths["restore_event"].unlink()
                metadata_check.reset_mock()
                self.assertEqual(
                    [],
                    VALIDATOR.validate_external_inputs(
                        main_only,
                        policy,
                        main_template,
                        restore_template,
                        paths["caddy_config"],
                        paths["caddy_compose"],
                        "steady",
                        "main",
                    ),
                )
                checked_labels = [call.args[1] for call in metadata_check.call_args_list]
                self.assertTrue(checked_labels)
                self.assertTrue(all(label.startswith("main ") for label in checked_labels))

                paths["restore_config"].write_bytes(restore_template.read_bytes())
                paths["restore_event"].write_text(
                    "<?php return ['listen'=>['restore'=>[]]];\n",
                    encoding="utf-8",
                )
                restore_only = copy.deepcopy(manifest)
                restore_only["generated_events"]["main"] = {
                    "state": "pending",
                    "sha256": None,
                }
                paths["main_config"].write_text("wrong main config\n", encoding="utf-8")
                paths["main_event"].unlink()
                metadata_check.reset_mock()
                self.assertEqual(
                    [],
                    VALIDATOR.validate_external_inputs(
                        restore_only,
                        policy,
                        main_template,
                        restore_template,
                        paths["caddy_config"],
                        paths["caddy_compose"],
                        "steady",
                        "restore",
                    ),
                )
                checked_labels = [call.args[1] for call in metadata_check.call_args_list]
                self.assertTrue(checked_labels)
                self.assertTrue(all(label.startswith("restore ") for label in checked_labels))

                paths["main_config"].write_bytes(main_template.read_bytes())
                paths["main_event"].write_text(
                    "<?php return ['listen'=>[]];\n",
                    encoding="utf-8",
                )
                broken_manifest = copy.deepcopy(manifest)
                broken_manifest["generated_events"]["restore"]["sha256"] = "0" * 64
                self.assertTrue(
                    VALIDATOR.validate_external_inputs(
                        broken_manifest,
                        policy,
                        main_template,
                        restore_template,
                        paths["caddy_config"],
                        paths["caddy_compose"],
                        "steady",
                        "both",
                    )
                )

                paths["main_event"].write_bytes(b"")
                paths["restore_event"].write_bytes(b"")
                bootstrap_manifest = copy.deepcopy(manifest)
                bootstrap_manifest["generated_events"] = {
                    "main": {"state": "pending", "sha256": None},
                    "restore": {"state": "pending", "sha256": None},
                }
                metadata_check.reset_mock()
                self.assertEqual(
                    [],
                    VALIDATOR.validate_external_inputs(
                        bootstrap_manifest,
                        policy,
                        main_template,
                        restore_template,
                        paths["caddy_config"],
                        paths["caddy_compose"],
                        "bootstrap",
                        "both",
                    ),
                )
                metadata_check.assert_any_call(
                    paths["main_event"],
                    "main generated event",
                    expected_mode=0o660,
                    require_nonempty=False,
                    allow_missing=True,
                )

                self.assertTrue(
                    VALIDATOR.validate_external_inputs(
                        bootstrap_manifest,
                        policy,
                        main_template,
                        restore_template,
                        paths["caddy_config"],
                        paths["caddy_compose"],
                        "bootstrap",
                        "invalid",
                    )
                )
                metadata_check.assert_any_call(
                    paths["restore_event"],
                    "restore generated event",
                    expected_mode=0o660,
                    require_nonempty=False,
                    allow_missing=True,
                )


class MysqlSecretHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.main = load_json("compose.yaml")
        self.restore = load_json("compose.restore.yaml")
        self.policy = load_json("stack-policy.json")
        self.wrapper = (DEPLOY / "mysql-entrypoint.sh").read_text(encoding="utf-8")
        self.healthcheck = (DEPLOY / "mysql-healthcheck.sh").read_text(encoding="utf-8")

    def assert_rejected(
        self,
        main: dict[str, Any] | None = None,
        restore: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        wrapper: str | None | object = ...,
    ) -> None:
        wrapper_value = self.wrapper if wrapper is ... else wrapper
        errors = mysql_handoff_errors(
            self.main if main is None else main,
            self.restore if restore is None else restore,
            self.policy if policy is None else policy,
            wrapper_value if isinstance(wrapper_value, str) else None,
        )
        self.assertTrue(errors, "unsafe mutation unexpectedly passed")

    def test_root_bootstrap_hands_secrets_to_non_root_mysql(self) -> None:
        self.assertEqual(
            [],
            mysql_handoff_errors(self.main, self.restore, self.policy, self.wrapper),
        )

    def test_missing_wrapper_and_group_10001_are_rejected(self) -> None:
        self.assert_rejected(wrapper=None)
        main = copy.deepcopy(self.main)
        main["services"]["db"]["group_add"] = [10001]
        self.assert_rejected(main=main)
        restore = copy.deepcopy(self.restore)
        restore["services"]["db"]["group_add"] = [10001]
        self.assert_rejected(restore=restore)

    def test_privilege_drop_and_private_tmpfs_mutations_are_rejected(self) -> None:
        self.assert_rejected(wrapper=self.wrapper.replace("exec gosu mysql ", "exec ", 1))
        self.assert_rejected(wrapper=self.wrapper.replace("chmod 0400", "chmod 0440", 1))
        self.assert_rejected(wrapper=self.wrapper.replace('chown 999:999 "${private_dir}"\n', "", 1))
        self.assert_rejected(
            wrapper=self.wrapper.replace(
                'chmod 0400 "${target_path}"\n    chown 999:999 "${target_path}"',
                'chown 999:999 "${target_path}"\n    chmod 0400 "${target_path}"',
                1,
            )
        )

        main = copy.deepcopy(self.main)
        main["services"]["db"]["tmpfs"] = [
            item for item in main["services"]["db"]["tmpfs"]
            if not item.startswith("/run/miaomu-db-secrets:")
        ]
        self.assert_rejected(main=main)

        main = copy.deepcopy(self.main)
        main["services"]["db"]["tmpfs"][-1] = main["services"]["db"]["tmpfs"][-1].replace(
            "mode=0700", "mode=0755"
        )
        self.assert_rejected(main=main)

    def test_steady_marker_branch_mutations_are_rejected(self) -> None:
        self.assert_rejected(
            wrapper=self.wrapper.replace(
                'if gosu mysql test -f "${steady_marker}"; then',
                'if test -f "${steady_marker}"; then',
                1,
            )
        )
        self.assert_rejected(
            wrapper=self.wrapper.replace(
                'if gosu mysql test -f "${steady_marker}"; then',
                'if ! gosu mysql test -f "${steady_marker}"; then',
                1,
            )
        )
        unset_line = (
            "unset MYSQL_PASSWORD_FILE MYSQL_ROOT_PASSWORD_FILE "
            "MYSQL_PASSWORD MYSQL_ROOT_PASSWORD"
        )
        self.assert_rejected(wrapper=self.wrapper.replace(unset_line, "", 1))
        for variable in (
            "MYSQL_PASSWORD_FILE",
            "MYSQL_ROOT_PASSWORD_FILE",
            "MYSQL_PASSWORD",
            "MYSQL_ROOT_PASSWORD",
        ):
            with self.subTest(missing_unset=variable):
                self.assert_rejected(wrapper=self.wrapper.replace(f" {variable}", "", 1))
        self.assert_rejected(
            wrapper=self.wrapper.replace(
                'exec gosu mysql "$@"',
                'exec gosu mysql /usr/local/bin/docker-entrypoint.sh "$@"',
                1,
            )
        )
        self.assert_rejected(
            wrapper=self.wrapper.replace(
                'exec gosu mysql "$@"',
                'touch "${steady_marker}"\n    exec gosu mysql "$@"',
                1,
            )
        )
        policy = copy.deepcopy(self.policy)
        policy["service_identities"]["db"]["steady_marker"] = "/var/lib/mysql/mysql"
        self.assert_rejected(policy=policy)

    def test_capability_mutations_are_rejected(self) -> None:
        for mutation in (
            ["CHOWN", "SETGID"],
            ["CHOWN", "SETGID", "SETUID", "DAC_OVERRIDE"],
            ["ALL"],
        ):
            main = copy.deepcopy(self.main)
            main["services"]["db"]["cap_add"] = mutation
            with self.subTest(capabilities=mutation):
                self.assert_rejected(main=main)

    def test_wrapper_does_not_emit_secret_content(self) -> None:
        commands = shell_commands(self.wrapper)
        self.assertNotIn("set -x", self.wrapper)
        self.assertNotIn("MYSQL_PASSWORD=", self.wrapper)
        self.assertNotIn("MYSQL_ROOT_PASSWORD=", self.wrapper)
        self.assertNotIn("$(", self.wrapper)
        for command in commands:
            if command:
                self.assertNotIn(command[0], {"cat", "tee", "env", "printenv", "base64", "xxd", "od"})

    def test_healthcheck_distinguishes_bootstrap_and_steady_state(self) -> None:
        self.assertEqual([], mysql_healthcheck_errors(self.healthcheck))
        mutations = (
            self.healthcheck.replace(
                "gosu mysql test -f /var/lib/mysql/.miaomu-steady",
                "test -f /var/lib/mysql/.miaomu-steady",
                1,
            ),
            self.healthcheck.replace(
                'if [ "${mode}" = "steady" ]; then',
                'if [ "${mode}" = "bootstrap" ]; then',
                1,
            ),
            self.healthcheck.replace(
                "gosu mysql test -f /var/lib/mysql/.miaomu-steady\n",
                "",
                1,
            ),
            self.healthcheck.replace(
                '"${mode}" != "bootstrap"',
                '"${mode}" != "anything"',
                1,
            ),
            self.healthcheck + "\ncat /run/secrets/mysql_root_password\n",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[:80]):
                self.assertTrue(mysql_healthcheck_errors(mutation))


class CaddyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (DEPLOY / "Caddyfile.miaomu").read_text(encoding="utf-8")
        self.mounts = load_json("caddy-mounts.json")

    def test_loopback_caddy_contract_is_literal_and_closed(self) -> None:
        self.assertEqual([], caddy_errors(self.source))
        self.assertEqual([], VALIDATOR.validate_caddy_mounts(self.mounts))

    def test_caddy_mutations_fail_closed(self) -> None:
        mutations = (
            self.source.replace("http://127.0.0.1:88", "http://0.0.0.0:88", 1),
            self.source.replace("respond @download 404\n", "", 1),
            self.source.replace("/var/www/html/public/admin.php", "{http.request.uri.path}", 1),
            self.source.replace("@scriptLike path_regexp", "@scriptLikeDisabled path_regexp", 1),
            self.source.replace("handle /index.php {", "handle /index.php* {", 1),
            self.source.replace("\troute {", "\troute {\n\t\tfile_server", 1),
            self.source.replace("@static file", "env PHP_VALUE auto_prepend_file=/tmp/x\n\t\t@static file", 1),
        )
        for source in mutations:
            with self.subTest(mutation=source[:80]):
                self.assertTrue(caddy_errors(source))

        mounts = copy.deepcopy(self.mounts)
        mounts["mounts"].append(
            {
                "type": "volume",
                "source": "miaomu_downloads",
                "target": "/var/www/html/public/download",
                "read_only": True,
            }
        )
        self.assertTrue(
            VALIDATOR.validate_caddy_mounts(mounts),
            "Caddy downloads mount mutation unexpectedly passed",
        )

    def test_caddy_receives_only_public_uploads_and_socket(self) -> None:
        targets = {item["target"]: item for item in self.mounts["mounts"]}
        self.assertEqual(
            {
                "/var/www/html/public",
                "/var/www/html/public/static/upload",
                "/run/miaomu-fpm",
            },
            set(targets),
        )
        self.assertTrue(all(item["read_only"] for item in targets.values()))
        for forbidden in ("miaomu_downloads", "miaomu_runtime", "miaomu_db_data", "/var/run/docker.sock"):
            self.assertNotIn(forbidden, json.dumps(self.mounts["mounts"], sort_keys=True))
        self.assertEqual([10001], self.mounts["supplemental_groups"])
        self.assertFalse(self.mounts["change_strategy"]["shared_stack_down_allowed"])


class AppRuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app_dir = DEPLOY / "docker" / "app"

    def test_runtime_sanitizer_is_bounded_and_runs_before_framework_start(self) -> None:
        entrypoint = (self.app_dir / "docker-entrypoint.sh").read_text(encoding="utf-8")
        sanitizer = RUNTIME_SANITIZER_PATH.read_text(encoding="utf-8")
        dockerfile = (self.app_dir / "Dockerfile").read_text(encoding="utf-8")
        self.assertEqual([], runtime_sanitize_errors(entrypoint, sanitizer, dockerfile))

        swapped_order = (
            entrypoint.replace(
                '/usr/local/bin/miaomu-runtime-sanitize "${MIAOMU_ENV:-}"',
                "__MIAOMU_SANITIZER__",
                1,
            )
            .replace(
                "php /usr/local/lib/miaomu/environment_check.php --startup",
                '/usr/local/bin/miaomu-runtime-sanitize "${MIAOMU_ENV:-}"',
                1,
            )
            .replace(
                "__MIAOMU_SANITIZER__",
                "php /usr/local/lib/miaomu/environment_check.php --startup",
                1,
            )
        )
        entrypoint_mutations = (
            entrypoint.replace("managed_start=false", "managed_start=true", 1),
            entrypoint.replace(
                '    && [ "${3:-}" = "initialize" ]; then',
                '    && [ -n "${3:-}" ]; then',
                1,
            ),
            entrypoint.replace(
                '/usr/local/bin/miaomu-runtime-sanitize "${MIAOMU_ENV:-}"',
                '/usr/local/bin/miaomu-runtime-sanitize "${4:-}"',
                1,
            ),
            swapped_order,
        )
        for mutation in entrypoint_mutations:
            with self.subTest(entrypoint_mutation=mutation[:80]):
                self.assertTrue(runtime_sanitize_errors(mutation, sanitizer, dockerfile))

        sanitizer_mutations = (
            sanitizer.replace("    cache \\", "    ../cache \\", 1),
            sanitizer.replace(
                'runtime_root="/var/www/html/runtime"',
                'runtime_root="${MIAOMU_RUNTIME_ROOT:-/var/www/html/runtime}"',
                1,
            ),
            sanitizer.replace(
                'find "$target" -xdev -mindepth 1 -delete',
                'rm -rf "$runtime_root"/*',
                1,
            ),
            sanitizer.replace(
                'find "$runtime_root" -xdev -type l -print -quit',
                'find "$runtime_root" -type l -print -quit',
                1,
            ),
            sanitizer.replace('[ ! -L "$runtime_root" ]', "true", 1),
            sanitizer.replace('[ -d "$target" ]', "true", 1),
            sanitizer.replace(
                'if [ "$mode" = "restore" ]; then\n'
                '    find "$runtime_root" -xdev -mindepth 1 -delete '
                '|| fail "cannot empty restore runtime"\n'
                "fi\n",
                'find "$runtime_root" -xdev -mindepth 1 -delete '
                '|| fail "cannot empty restore runtime"\n',
                1,
            ),
        )
        for mutation in sanitizer_mutations:
            self.assertNotEqual(sanitizer, mutation)
            with self.subTest(sanitizer_mutation=mutation[:80]):
                self.assertTrue(runtime_sanitize_errors(entrypoint, mutation, dockerfile))

        dockerfile_mutations = (
            dockerfile.replace(
                "COPY --chown=0:0 deploy/docker/app/runtime-sanitize.sh",
                "COPY --chown=10001:10001 deploy/docker/app/runtime-sanitize.sh",
                1,
            ),
            dockerfile.replace("        /usr/local/bin/miaomu-runtime-sanitize \\\n", "", 1),
        )
        for mutation in dockerfile_mutations:
            self.assertNotEqual(dockerfile, mutation)
            with self.subTest(dockerfile_mutation=mutation[:80]):
                self.assertTrue(runtime_sanitize_errors(entrypoint, sanitizer, mutation))

    def test_fpm_uses_only_the_authorized_unix_socket(self) -> None:
        pool = (self.app_dir / "www.conf").read_text(encoding="utf-8")
        guard = (self.app_dir / "fpm-entry-guard.php").read_text(encoding="utf-8")
        self.assertEqual([], fpm_errors(pool, guard))

    def test_fpm_guard_allows_only_three_real_entrypoints(self) -> None:
        source = (self.app_dir / "fpm-entry-guard.php").read_text(encoding="utf-8")
        self.assertIn("/var/www/html/public/", source)
        for entrypoint in ("index.php", "admin.php", "api.php"):
            literal = f"/var/www/html/public/{entrypoint}"
            split_literal = f"'{entrypoint}'"
            self.assertTrue(literal in source or split_literal in source)
        self.assertIn("PHP_SAPI", source)
        self.assertIn("fpm-fcgi", source)
        self.assertIn("SCRIPT_FILENAME", source)
        self.assertIn("PATH_INFO", source)
        self.assertTrue("realpath" in source or "str_replace" in source)
        for forbidden in ("PHP_VALUE", "PHP_ADMIN_VALUE", "HTTP_"):
            self.assertNotIn(forbidden, source)

    def test_fpm_tcp_and_guard_mutations_fail_closed(self) -> None:
        pool = (self.app_dir / "www.conf").read_text(encoding="utf-8")
        guard = (self.app_dir / "fpm-entry-guard.php").read_text(encoding="utf-8")
        mutations = (
            (pool.replace("listen = /run/miaomu-fpm/php-fpm.sock", "listen = 127.0.0.1:9000", 1), guard),
            (
                pool.replace(
                    "php_admin_value[auto_prepend_file] = /usr/local/lib/miaomu/fpm-entry-guard.php\n",
                    "",
                    1,
                ),
                guard,
            ),
            (pool, ""),
            (pool, guard.replace("'PATH_INFO', ", "", 1)),
            (pool, guard.replace("realpath($scriptFilename)", "$scriptFilename", 1)),
        )
        for mutated_pool, mutated_guard in mutations:
            with self.subTest(pool=mutated_pool[:40], guard=mutated_guard[:40]):
                self.assertTrue(
                    fpm_errors(mutated_pool, mutated_guard),
                    "unsafe FPM mutation unexpectedly passed",
                )

    def test_database_template_reads_only_the_file_secret(self) -> None:
        main = (DEPLOY / "config" / "database.php.example").read_text(encoding="utf-8")
        restore = (DEPLOY / "config" / "database.restore.php.example").read_text(encoding="utf-8")
        self.assertEqual([], database_template_errors(main, "miaomu", "miaomu_app"))
        self.assertEqual(
            [],
            database_template_errors(restore, "miaomu_restore", "miaomu_restore_app"),
        )
        self.assertNotEqual(main, restore)

        mutations = (
            (main.replace('str_contains($databaseCredential, "\\0")', "false"), "miaomu", "miaomu_app"),
            (main.replace("'database'        => 'miaomu'", "'database'        => 'miaomu_restore'"), "miaomu", "miaomu_app"),
            (restore.replace("'username'        => 'miaomu_restore_app'", "'username'        => 'miaomu_app'"), "miaomu_restore", "miaomu_restore_app"),
            (
                main.replace(
                    "@file_get_contents($secretPath)",
                    "getenv('MIAOMU_DATABASE_CREDENTIAL')",
                    1,
                ),
                "miaomu",
                "miaomu_app",
            ),
            (
                main.replace(
                    "$databaseCredential = @file_get_contents($secretPath);",
                    "$databaseCredential = 'hardcoded-credential';",
                    1,
                ),
                "miaomu",
                "miaomu_app",
            ),
            (
                main.replace("('pass'.'word')", "'password'", 1),
                "miaomu",
                "miaomu_app",
            ),
        )
        for source, database, username in mutations:
            with self.subTest(database=database, username=username):
                self.assertTrue(database_template_errors(source, database, username))

    def test_dockerfile_has_pinned_build_inputs_and_no_composer_in_runtime(self) -> None:
        source = (self.app_dir / "Dockerfile").read_text(encoding="utf-8")
        policy = load_json("stack-policy.json")
        self.assertIn(policy["images"]["php_base"]["reference"], source)
        self.assertIn(policy["images"]["composer"]["reference"], source)
        self.assertRegex(source, r"(?m)^FROM\s+\S+\s+AS\s+runtime\s*$")
        self.assertIn("composer install", source)
        self.assertIn("composer check-platform-reqs", source)
        self.assertIn("environment_check.php", source)
        self.assertIn("nursery-bootstrap.php", source)
        self.assertIn("/usr/local/lib/miaomu/nursery-bootstrap.php", source)
        self.assertIn("install -o 0 -g 0 -m 0444 /dev/null /var/www/html/app/event.php", source)
        runtime = source.split(" AS runtime", 1)[-1]
        self.assertNotRegex(runtime, r"(?m)^COPY\s+--from=composer[^\n]*/usr/bin/composer")
        self.assertNotIn("EXPOSE 9000", source)

    def test_official_nursery_bootstrap_contract_and_mutations(self) -> None:
        source = (self.app_dir / "nursery-bootstrap.php").read_text(encoding="utf-8")
        self.assertEqual([], event_bootstrap_errors(source))
        mutations = (
            source.replace("PluginsAdminService::PluginsInstall", "NurseryInstall", 1),
            source.replace("PluginsAdminService::PluginsStatusUpdate", "NurseryStatusUpdate", 1),
            source.replace("CatalogMigration::Run('existing', $actor, $runId)", "[]", 1),
            source.replace("array_diff($enabled, ['nursery'])", "[]", 1),
            source.replace("$enabled !== ['nursery']", "false", 1),
            source.replace("!== 0660", "!== 0666", 1),
            source.replace('return [];\\n";', "return ['listen'=>[]];\\n\";", 1),
            source.replace("$safeEventStub, LOCK_EX", "$safeEventStub", 1),
            source + "\nfile_put_contents($eventPath, '<?php return [];');\n",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[:80]):
                self.assertTrue(event_bootstrap_errors(mutation))

    def test_environment_readiness_checks_generated_event_and_plugin_set(self) -> None:
        source = (ROOT / "tests" / "ops" / "environment_check.php").read_text(encoding="utf-8")
        self.assertEqual([], readiness_errors(source))
        mutations = (
            source.replace("!is_writable($eventPath)", "true", 1),
            source.replace(
                "(($eventStat['mode'] ?? 0) & 0777) === 0440",
                "(($eventStat['mode'] ?? 0) & 0777) === 0660",
                1,
            ),
            source.replace("$events['listen'] === $pluginConfig['hook']", "true", 1),
            source.replace("$enabledPlugins === ['nursery']", "true", 1),
            source.replace("plugins_nursery_catalog_manifest", "plugins_other", 1),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation[:80]):
                self.assertTrue(readiness_errors(mutation))


class DocumentationContractTests(unittest.TestCase):
    def test_runtime_claims_remain_not_run(self) -> None:
        required = {
            "DEPLOYMENT.md": ("NUR-OPS-001", "not_run", "127.0.0.1:88", "jia-caddy"),
            "LOCAL_STACK.md": ("NUR-OPS-001", "not_run", "Unix socket", "root-only", "私有 tmpfs"),
            "BACKUP_RESTORE.md": ("not_run", "miaomu_restore", "miaomu_restore_fpm_socket"),
            "PERFORMANCE_BASELINE.md": ("not_run", "P50", "P95", "错误率"),
        }
        for filename, fragments in required.items():
            source = (DOCS / filename).read_text(encoding="utf-8")
            with self.subTest(document=filename):
                for fragment in fragments:
                    self.assertIn(fragment, source)

    def test_performance_protocol_covers_all_required_scenarios(self) -> None:
        source = (DOCS / "PERFORMANCE_BASELINE.md").read_text(encoding="utf-8")
        for scenario in ("商品列表", "商品详情", "收藏", "询价", "行为上报", "后台 30 日趋势", "数据导出"):
            self.assertIn(scenario, source)
        for fingerprint in ("Git release SHA", "Caddy", "PHP", "MySQL", "数据集规模"):
            self.assertIn(fingerprint, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
