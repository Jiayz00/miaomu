#!/bin/sh
set -eu

mode="${1:-}"
if [ "$#" -ne 1 ] || { [ "${mode}" != "bootstrap" ] && [ "${mode}" != "steady" ]; }; then
    exit 2
fi

gosu mysql mysqladmin ping --protocol=socket --silent >/dev/null 2>&1

if [ "${mode}" = "steady" ]; then
    gosu mysql test -f /var/lib/mysql/.miaomu-steady
fi
