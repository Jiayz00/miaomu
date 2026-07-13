#!/bin/sh
set -eu

fail()
{
    printf '%s\n' "[miaomu-entrypoint] startup contract failed: $1" >&2
    exit 78
}

[ "$(id -u)" = "10001" ] || fail "unexpected uid"
[ "$(id -g)" = "10001" ] || fail "unexpected gid"

[ -f /var/www/html/config/database.php ] || fail "database config missing"
[ -r /var/www/html/config/database.php ] || fail "database config unreadable"
[ ! -w /var/www/html/config/database.php ] || fail "database config is writable"

[ -f /run/secrets/mysql_app_password ] || fail "database secret missing"
[ -r /run/secrets/mysql_app_password ] || fail "database secret unreadable"
[ -s /run/secrets/mysql_app_password ] || fail "database secret empty"

for path in \
    /var/www/html/runtime \
    /var/www/html/public/static/upload \
    /var/www/html/public/download \
    /run/miaomu-fpm \
    /tmp
do
    [ -d "$path" ] || fail "required writable directory missing"
    [ -w "$path" ] || fail "required writable directory is not writable"
done

for path in \
    /var/www/html/app \
    /var/www/html/config \
    /var/www/html/extend \
    /var/www/html/public/index.php \
    /var/www/html/public/admin.php \
    /var/www/html/public/api.php
do
    [ -e "$path" ] || fail "required source path missing"
    [ ! -w "$path" ] || fail "protected source path is writable"
done

release_sha="$(tr -d '\r\n' < /usr/local/share/miaomu/release-sha)"
[ "${MIAOMU_RELEASE_SHA:-}" = "$release_sha" ] || fail "release revision mismatch"

socket_path="/run/miaomu-fpm/php-fpm.sock"
managed_start=false
if [ "${1:-}" = "php-fpm" ]; then
    managed_start=true
elif [ "${1:-}" = "php" ] \
    && [ "${2:-}" = "/usr/local/lib/miaomu/nursery-bootstrap.php" ] \
    && [ "${3:-}" = "initialize" ]; then
    managed_start=true
fi

if [ "$managed_start" = "true" ]; then
    /usr/local/bin/miaomu-runtime-sanitize "${MIAOMU_ENV:-}" \
        || fail "runtime sanitization failed"
fi

if [ "${1:-}" = "php-fpm" ]; then
    [ -f /var/www/html/app/event.php ] || fail "generated event missing"
    [ -s /var/www/html/app/event.php ] || fail "generated event empty"
    [ -r /var/www/html/app/event.php ] || fail "generated event unreadable"
    [ ! -w /var/www/html/app/event.php ] || fail "generated event is writable"
    php /usr/local/lib/miaomu/environment_check.php --startup >/dev/null \
        || fail "application readiness failed"
    if [ -e "$socket_path" ] || [ -L "$socket_path" ]; then
        [ -S "$socket_path" ] || fail "stale socket path is not a Unix socket"
        rm -f "$socket_path"
    fi
fi

umask 0027
exec "$@"
