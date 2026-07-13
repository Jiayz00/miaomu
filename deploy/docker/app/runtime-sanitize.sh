#!/bin/sh
set -eu

fail()
{
    printf '%s\n' "[miaomu-runtime-sanitize] $1" >&2
    exit 78
}

[ "$#" -eq 1 ] || fail "expected one environment argument"
mode="$1"
case "$mode" in
    production|restore) ;;
    *) fail "unsupported environment" ;;
esac

runtime_root="/var/www/html/runtime"
[ -d "$runtime_root" ] || fail "runtime root missing"
[ ! -L "$runtime_root" ] || fail "runtime root must not be a symlink"
[ "$(readlink -f "$runtime_root")" = "$runtime_root" ] || fail "runtime root is not canonical"

if find "$runtime_root" -xdev -type l -print -quit | grep -q .; then
    fail "runtime contains a symlink"
fi

if [ "$mode" = "restore" ]; then
    find "$runtime_root" -xdev -mindepth 1 -delete || fail "cannot empty restore runtime"
fi

for relative_path in \
    cache \
    session \
    temp \
    admin/temp \
    index/temp \
    api/temp \
    data/config_data
do
    target="$runtime_root/$relative_path"
    case "$target" in
        "$runtime_root"/*) ;;
        *) fail "runtime cleanup target escaped root" ;;
    esac
    if [ -e "$target" ]; then
        [ -d "$target" ] || fail "runtime cleanup target is not a directory"
        find "$target" -xdev -mindepth 1 -delete || fail "cannot clear runtime directory"
    else
        mkdir -p "$target" || fail "cannot create runtime directory"
    fi
    chmod 0770 "$target" || fail "cannot set runtime directory mode"
done
