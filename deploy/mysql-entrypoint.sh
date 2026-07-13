#!/bin/sh
set -eu

readonly source_dir="/run/secrets"
readonly private_dir="/run/miaomu-db-secrets"
readonly steady_marker="/var/lib/mysql/.miaomu-steady"

if gosu mysql test -f "${steady_marker}"; then
    unset MYSQL_PASSWORD_FILE MYSQL_ROOT_PASSWORD_FILE MYSQL_PASSWORD MYSQL_ROOT_PASSWORD
    exec gosu mysql "$@"
fi

install -d -o 0 -g 0 -m 0700 "${private_dir}"

copy_secret() {
    name="$1"
    source_path="${source_dir}/${name}"
    target_path="${private_dir}/${name}"

    if [ ! -f "${source_path}" ] || [ -L "${source_path}" ] || [ ! -s "${source_path}" ]; then
        echo "required database secret metadata is invalid: ${name}" >&2
        exit 1
    fi

    cp -- "${source_path}" "${target_path}"
    chmod 0400 "${target_path}"
    chown 999:999 "${target_path}"
}

umask 077
copy_secret mysql_app_password
copy_secret mysql_root_password
chown 999:999 "${private_dir}"

export MYSQL_PASSWORD_FILE="${private_dir}/mysql_app_password"
export MYSQL_ROOT_PASSWORD_FILE="${private_dir}/mysql_root_password"

# This first process is bootstrap-only. NUR-OPS-001 must restart it after the
# initial health gate; the branch above then starts mysqld without credentials.
exec gosu mysql /usr/local/bin/docker-entrypoint.sh "$@"
