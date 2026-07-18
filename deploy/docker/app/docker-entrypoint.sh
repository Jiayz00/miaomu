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

inquiry_secret_path="/run/secrets/nursery_inquiry_hmac_key"
[ -f "$inquiry_secret_path" ] || fail "inquiry secret missing"
[ ! -L "$inquiry_secret_path" ] || fail "inquiry secret must not be a symlink"
[ -r "$inquiry_secret_path" ] || fail "inquiry secret unreadable"
[ -s "$inquiry_secret_path" ] || fail "inquiry secret empty"

# The secret is supplied by an external file secret. Read one bounded line
# without printing it, then expose it only to the FPM environment contract.
inquiry_key=""
inquiry_extra=""
exec 3< "$inquiry_secret_path"
IFS= read -r inquiry_key <&3 || [ -n "$inquiry_key" ] || fail "inquiry secret read failed"
if IFS= read -r inquiry_extra <&3 || [ -n "$inquiry_extra" ]; then
    exec 3<&-
    fail "inquiry secret must contain one line"
fi
exec 3<&-
[ "${#inquiry_key}" -ge 32 ] || fail "inquiry secret too short"
[ "${#inquiry_key}" -le 4096 ] || fail "inquiry secret too long"
export PHP_NURSERY_INQUIRY_HMAC_KEY="$inquiry_key"
unset inquiry_key inquiry_extra

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
    && [ "${2:-}" = "/usr/local/lib/miaomu/shopxo-schema-bootstrap.php" ] \
    && [ "${3:-}" = "initialize" ]; then
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
