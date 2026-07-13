from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = ROOT / "app" / "plugins" / "nursery"
CONFIG_FILE = PLUGIN_ROOT / "config.json"
HOOK_FILE = PLUGIN_ROOT / "Hook.php"
EVENT_FILE = PLUGIN_ROOT / "Event.php"
POLICY_FILE = PLUGIN_ROOT / "service" / "ScopePolicy.php"
USER_VIEW_FILE = PLUGIN_ROOT / "view" / "index" / "user" / "index.html"
LIST_VIEW_FILE = PLUGIN_ROOT / "view" / "index" / "module" / "goods" / "list" / "base.html"
SLIDER_VIEW_FILE = PLUGIN_ROOT / "view" / "index" / "module" / "goods" / "slider" / "binding.html"
UPSTREAM_LIST_VIEW_FILE = ROOT / "app" / "index" / "view" / "default" / "module" / "goods" / "list" / "base.html"
UPSTREAM_SLIDER_VIEW_FILE = (
    ROOT / "app" / "index" / "view" / "default" / "module" / "goods" / "slider" / "binding.html"
)

HOOK_CLASS = r"app\plugins\nursery\Hook"

EXPECTED_HOOKS = (
    "plugins_service_system_begin",
    "plugins_service_navigation_header_handle",
    "plugins_service_navigation_footer_handle",
    "plugins_service_header_navigation_top_right_handle",
    "plugins_service_quick_navigation_pc",
    "plugins_service_quick_navigation_h5",
    "plugins_service_app_home_navigation_h5",
    "plugins_service_app_user_center_navigation_h5",
    "plugins_service_bottom_navigation_handle",
    "plugins_service_users_center_left_menu_handle",
    "plugins_service_user_center_mini_navigation_handle",
    "plugins_service_admin_menu_data",
    "plugins_service_goods_buy_nav_button_handle",
    "plugins_view_assign_data",
    "plugins_view_fetch_begin",
)

NAVIGATION_HOOKS = (
    "plugins_service_navigation_header_handle",
    "plugins_service_navigation_footer_handle",
    "plugins_service_header_navigation_top_right_handle",
    "plugins_service_quick_navigation_pc",
    "plugins_service_quick_navigation_h5",
    "plugins_service_app_home_navigation_h5",
    "plugins_service_app_user_center_navigation_h5",
    "plugins_service_bottom_navigation_handle",
    "plugins_service_users_center_left_menu_handle",
    "plugins_service_user_center_mini_navigation_handle",
)

WEB_DENIED = (
    "buy",
    "cart",
    "order",
    "orderaftersale",
    "pay",
    "useraddress",
    "usergoodscomments",
    "userintegral",
)

API_DENIED = (
    "buy",
    "cart",
    "cashier",
    "order",
    "orderaftersale",
    "ordernotify",
    "paylog",
    "useraddress",
    "usergoodscomments",
    "userintegral",
)

ADMIN_DENIED = (
    "express",
    "goodscart",
    "goodscomments",
    "integrallog",
    "order",
    "orderaftersale",
    "payment",
    "paylog",
    "payrequestlog",
    "refundlog",
    "warehouse",
    "warehousegoods",
)

PX_PLUGINS = (
    "agent",
    "aftersale",
    "bargain",
    "cart",
    "coupon",
    "delivery",
    "distribution",
    "finance",
    "groupbuy",
    "integral",
    "inventory",
    "live",
    "memberlevel",
    "membership",
    "merchant",
    "multimerchant",
    "order",
    "payment",
    "points",
    "refund",
    "seckill",
    "supplier",
    "wallet",
)

PX_PLUGIN_ALIASES = (
    "excellentbuyreturntocash",
    "membershiplevelvip",
    "shop",
    "weixinliveplayer",
)

HIDDEN_PLUGIN_ENTRIES = (
    "activity",
    "blog",
    "signin",
    "ask",
    "brand",
    "realstore",
    "binding",
    "invoice",
)

WEB_ALLOWED = (
    "index",
    "category",
    "search",
    "goods",
    "user",
    "personal",
    "safety",
    "usergoodsfavor",
    "usergoodsbrowse",
    "message",
    "plugins",
)

API_ALLOWED = WEB_ALLOWED

ADMIN_ALLOWED = (
    "goods",
    "goodscategory",
    "goodsspectemplate",
    "goodsparamstemplate",
    "user",
    "goodsfavor",
    "goodsbrowse",
    "site",
    "navigation",
    "role",
    "power",
)

POLICY_CONSTANTS = {
    "WEB_DENIED_CONTROLLERS": WEB_DENIED,
    "API_DENIED_CONTROLLERS": API_DENIED,
    "ADMIN_DENIED_CONTROLLERS": ADMIN_DENIED,
    "DENIED_PLUGINS": PX_PLUGINS,
    "WEB_ALLOWED_CONTROLLERS": WEB_ALLOWED,
    "API_ALLOWED_CONTROLLERS": API_ALLOWED,
    "ADMIN_ALLOWED_CONTROLLERS": ADMIN_ALLOWED,
}

ADMIN_PAYLOAD_KEYS = (
    "admin_left_menu",
    "admin_power",
    "admin_plugins",
    "admin_all_plugins",
)

STRUCTURED_NAVIGATION_FIELDS = (
    "control",
    "controller",
    "url",
    "value",
    "event_value",
    "only_tag",
    "type",
)

PATHINFO_H5_MARKERS = (
    "pages/cart-page",
    "pages/paylog-detail",
    "pages/paylog-list",
    "pages/user-order-detail",
    "pages/user-order-history",
    "pages/user-goods-comments",
)

DEFAULT_THEME_VIEW_REPLACEMENTS = {
    "module/goods/list/base": "../../../plugins/nursery/view/index/module/goods/list/base",
    "module/goods/slider/binding": "../../../plugins/nursery/view/index/module/goods/slider/binding",
}

DEFAULT_FALLBACK_VIEW_REPLACEMENTS = {
    "../default/module/goods/list/base": "../../../plugins/nursery/view/index/module/goods/list/base",
    "../default/module/goods/slider/binding": "../../../plugins/nursery/view/index/module/goods/slider/binding",
}

EXPECTED_PLUGIN_FILES = {
    "config.json",
    "Event.php",
    "Hook.php",
    "service/ScopePolicy.php",
    "view/index/module/goods/list/base.html",
    "view/index/module/goods/slider/binding.html",
    "view/index/user/index.html",
}

EXPECTED_EVENT_METHODS = (
    "Upload",
    "BeginInstall",
    "Install",
    "Uninstall",
    "Download",
    "BeginUpgrade",
    "Upgrade",
    "Delete",
)

EXPECTED_USER_VIEW_HOOKS = (
    "plugins_view_user_center_top",
    "plugins_view_user_base_bottom",
    "plugins_view_user_various_top",
    "plugins_view_user_various_inside_top",
    "plugins_view_user_various_inside_bottom",
    "plugins_view_user_various_bottom",
)

EXPECTED_GOODS_VIEW_HOOKS = (
    "plugins_view_module_goods_inside_top",
    "plugins_view_module_goods_inside_price_top",
    "plugins_view_module_goods_inside_bottom",
)

FORBIDDEN_GOODS_CART_MARKERS = (
    "common-goods-cart-submit-event",
    "icon-shopping-cart",
    "item-cart-submit",
    "goods-cart",
)

LIST_CART_NODE = (
    '                                    <i data-gid="{{$v.id}}" data-is-many-spec="{{$v.is_exist_many_spec}}" '
    'class="goods-cart iconfont icon-shopping-cart login-event common-goods-cart-submit-event '
    'am-color-main am-cursor-pointer"></i>\n'
)

SLIDER_CART_NODE = (
    "                                        {{if $v['is_error'] eq 0}}\n"
    '                                            <a href="javascript:;" data-gid="{{$v.id}}" '
    'data-is-many-spec="{{$v.is_exist_many_spec}}" '
    'class="item-cart-submit am-fl common-goods-cart-submit-event">\n'
    '                                                <i class="iconfont icon-shopping-cart"></i>\n'
    '                                            </a>\n'
    "                                        {{/if}}\n"
)


class ContractError(AssertionError):
    """Raised when a static nursery scope contract is incomplete or widened."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def read_utf8(path: Path) -> str:
    require(path.is_file(), f"required file is missing: {display_path(path)}")
    require(not path.is_symlink(), f"required file must not be a symlink: {path}")
    data = path.read_bytes()
    require(b"\x00" not in data, f"NUL byte found in text contract: {path}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"file is not UTF-8: {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_code(source: str) -> str:
    return re.sub(r"\s+", "", source).lower()


def strict_json_loads(source: str) -> dict[str, Any]:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(source, object_pairs_hook=no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid config.json: {exc}") from exc
    require(isinstance(value, dict), "config.json root must be an object")
    return value


def _matching_delimiter(source: str, start: int, opening: str, closing: str) -> int:
    require(start < len(source) and source[start] == opening, "invalid delimiter start")
    depth = 0
    state = "normal"
    escaped = False
    index = start
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if state in {"single", "double"}:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif (state == "single" and char == "'") or (state == "double" and char == '"'):
                state = "normal"
            index += 1
            continue

        if state == "line_comment":
            if char in "\r\n":
                state = "normal"
            index += 1
            continue

        if state == "block_comment":
            if char == "*" and next_char == "/":
                state = "normal"
                index += 2
            else:
                index += 1
            continue

        if char == "'":
            state = "single"
        elif char == '"':
            state = "double"
        elif char == "/" and next_char == "/":
            state = "line_comment"
            index += 2
            continue
        elif char == "/" and next_char == "*":
            state = "block_comment"
            index += 2
            continue
        elif char == "#":
            state = "line_comment"
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ContractError(f"unclosed delimiter {opening}{closing}")


def php_const_body_span(source: str, name: str) -> tuple[int, int]:
    match = re.search(
        rf"\b(?:(?:public|protected|private)\s+)?const\s+{re.escape(name)}\s*=\s*\[",
        source,
        flags=re.IGNORECASE,
    )
    require(match is not None, f"missing direct PHP constant: {name}")
    opening = source.find("[", match.start())
    closing = _matching_delimiter(source, opening, "[", "]")
    return opening + 1, closing


PHP_STRING_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")


def _decode_php_string(literal: str) -> str:
    quote = literal[0]
    body = literal[1:-1]
    if quote == "'":
        return body.replace(r"\'", "'").replace(r"\\", "\\")
    return (
        body.replace(r'\"', '"')
        .replace(r"\\", "\\")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
    )


def extract_php_const_list(source: str, name: str) -> tuple[str, ...]:
    start, end = php_const_body_span(source, name)
    body = source[start:end]
    matches = list(PHP_STRING_LITERAL.finditer(body))
    values: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        separator = body[cursor : match.start()]
        if index == 0:
            require(separator.strip() == "", f"{name} must be a direct string list")
        else:
            require(
                separator.count(",") == 1 and separator.replace(",", "").strip() == "",
                f"{name} contains a dynamic or malformed list element",
            )
        values.append(_decode_php_string(match.group(0)))
        cursor = match.end()

    tail = body[cursor:]
    require(
        tail.strip() in {"", ","},
        f"{name} must contain only direct string literals",
    )
    require(len(values) == len(set(values)), f"{name} contains duplicate values")
    return tuple(values)


def extract_php_const_map(source: str, name: str) -> dict[str, str]:
    start, end = php_const_body_span(source, name)
    body = source[start:end]
    entry_pattern = re.compile(
        rf"(?P<key>{PHP_STRING_LITERAL.pattern})\s*=>\s*(?P<value>{PHP_STRING_LITERAL.pattern})"
    )
    result: dict[str, str] = {}
    cursor = 0
    for index, match in enumerate(entry_pattern.finditer(body)):
        separator = body[cursor : match.start()]
        if index == 0:
            require(separator.strip() == "", f"{name} must be a direct string map")
        else:
            require(
                separator.count(",") == 1 and separator.replace(",", "").strip() == "",
                f"{name} contains a dynamic or malformed map entry",
            )
        key = _decode_php_string(match.group("key"))
        value = _decode_php_string(match.group("value"))
        require(key not in result, f"{name} contains duplicate key: {key}")
        result[key] = value
        cursor = match.end()

    tail = body[cursor:]
    require(tail.strip() in {"", ","}, f"{name} must contain only direct string mappings")
    require(result, f"{name} must not be empty")
    return result


def php_method_span(source: str, name: str) -> tuple[int, int]:
    match = re.search(rf"\bfunction\s+{re.escape(name)}\s*\(", source, flags=re.IGNORECASE)
    require(match is not None, f"missing PHP method: {name}")
    opening = source.find("{", match.end())
    require(opening >= 0, f"missing body for PHP method: {name}")
    closing = _matching_delimiter(source, opening, "{", "}")
    return match.start(), closing + 1


def extract_php_method(source: str, name: str) -> str:
    start, end = php_method_span(source, name)
    return source[start:end]


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    require(count == 1, f"mutation target {label!r} must occur once, got {count}")
    return source.replace(old, new, 1)


def mutate_method_once(source: str, method: str, old: str, new: str, label: str) -> str:
    start, end = php_method_span(source, method)
    body = source[start:end]
    mutated = replace_once(body, old, new, label)
    return source[:start] + mutated + source[end:]


def mutate_const_remove_item(source: str, const_name: str, value: str) -> str:
    start, end = php_const_body_span(source, const_name)
    body = source[start:end]
    pattern = re.compile(rf"(?m)^[ \t]*['\"]{re.escape(value)}['\"][ \t]*,[ \t]*(?:\r?\n)?")
    mutated, count = pattern.subn("", body, count=1)
    require(count == 1, f"unable to remove {value!r} from {const_name}")
    return source[:start] + mutated + source[end:]


def mutate_const_remove_map_entry(source: str, const_name: str, key: str) -> str:
    start, end = php_const_body_span(source, const_name)
    body = source[start:end]
    pattern = re.compile(
        rf"(?m)^[ \t]*['\"]{re.escape(key)}['\"][ \t]*=>[ \t]*"
        rf"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")[ \t]*,[ \t]*(?:\r?\n)?"
    )
    mutated, count = pattern.subn("", body, count=1)
    require(count == 1, f"unable to remove mapping {key!r} from {const_name}")
    return source[:start] + mutated + source[end:]


def normalize_newlines(source: str) -> str:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip(" \t") for line in normalized.split("\n"))
    return normalized[:-1] if normalized.endswith("\n") else normalized


@contextmanager
def temporary_copy(original: Path, content: str) -> Iterator[Path]:
    original_hash = sha256_file(original)
    with tempfile.TemporaryDirectory(prefix="nursery-scope-contract-") as directory:
        temporary_path = Path(directory).resolve() / original.name
        require(
            not temporary_path.is_relative_to(ROOT.resolve()),
            "negative mutation copy must stay outside the repository",
        )
        temporary_path.write_text(content, encoding="utf-8", newline="\n")
        try:
            yield temporary_path
        finally:
            require(
                sha256_file(original) == original_hash,
                f"negative mutation changed working-tree file: {original}",
            )


def validate_manifest_source(source: str) -> dict[str, Any]:
    config = strict_json_loads(source)
    require(set(config) == {"base", "extend", "hook"}, "config.json top-level keys changed")
    base = config.get("base")
    hooks = config.get("hook")
    require(isinstance(base, dict), "config.json base must be an object")
    require(isinstance(hooks, dict), "config.json hook must be an object")
    require(base.get("plugins") == "nursery", "plugin identifier must be nursery")
    require(base.get("version") == "1.0.0", "plugin version must be explicit")
    require(base.get("apply_terminal") == ["pc", "h5"], "plugin terminals must be pc and h5")
    require(base.get("apply_version") == ["6.9.0"], "plugin must pin ShopXO 6.9.0")
    require(base.get("is_home") is False, "scope plugin must not expose a standalone homepage")
    require(tuple(hooks.keys()) == EXPECTED_HOOKS, "config.json must register the exact 15 hooks")
    for hook_name, listeners in hooks.items():
        require(listeners == [HOOK_CLASS], f"unexpected listener mapping for {hook_name}")
    return config


def validate_manifest_file(path: Path) -> dict[str, Any]:
    return validate_manifest_source(read_utf8(path))


def validate_policy_source(source: str) -> dict[str, tuple[str, ...]]:
    parsed: dict[str, tuple[str, ...]] = {}
    for name, expected in POLICY_CONSTANTS.items():
        actual = extract_php_const_list(source, name)
        require(actual == expected, f"{name} differs from the approved fixed set")
        require(all(item == item.lower().strip() for item in actual), f"{name} must be normalized")
        parsed[name] = actual

    for denied_name, allowed_name in (
        ("WEB_DENIED_CONTROLLERS", "WEB_ALLOWED_CONTROLLERS"),
        ("API_DENIED_CONTROLLERS", "API_ALLOWED_CONTROLLERS"),
        ("ADMIN_DENIED_CONTROLLERS", "ADMIN_ALLOWED_CONTROLLERS"),
    ):
        overlap = set(parsed[denied_name]) & set(parsed[allowed_name])
        require(not overlap, f"positive controllers entered deny set: {sorted(overlap)}")
    require("nursery" not in parsed["DENIED_PLUGINS"], "nursery plugin must remain reachable")

    plugin_aliases = extract_php_const_list(source, "DENIED_PLUGIN_ALIASES")
    require(
        len(plugin_aliases) == len(PX_PLUGIN_ALIASES) and set(plugin_aliases) == set(PX_PLUGIN_ALIASES),
        "DENIED_PLUGIN_ALIASES must contain exactly the four verified ShopXO direct aliases",
    )
    require(not set(plugin_aliases) & set(parsed["DENIED_PLUGINS"]), "plugin aliases duplicate canonical PX identifiers")
    parsed["DENIED_PLUGIN_ALIASES"] = plugin_aliases

    hidden_entries = extract_php_const_list(source, "HIDDEN_PLUGIN_ENTRIES")
    require(
        len(hidden_entries) == len(HIDDEN_PLUGIN_ENTRIES) and set(hidden_entries) == set(HIDDEN_PLUGIN_ENTRIES),
        "HIDDEN_PLUGIN_ENTRIES must contain exactly the eight entry-only identifiers",
    )
    require(
        not set(hidden_entries) & (set(parsed["DENIED_PLUGINS"]) | set(plugin_aliases)),
        "entry-only identifiers must stay outside the permanent direct deny sets",
    )
    parsed["HIDDEN_PLUGIN_ENTRIES"] = hidden_entries

    route_markers = extract_php_const_list(source, "DENIED_ROUTE_MARKERS")
    require(route_markers, "DENIED_ROUTE_MARKERS must not be empty")
    require(len(route_markers) == len(set(route_markers)), "DENIED_ROUTE_MARKERS has duplicates")
    require(all(marker == marker.lower().strip() for marker in route_markers), "route markers must be normalized")
    for controller in WEB_DENIED:
        require(
            f"index/{controller}" in route_markers,
            f"navigation route marker missing for Web controller: {controller}",
        )
    for controller in WEB_ALLOWED:
        require(
            f"index/{controller}" not in route_markers,
            f"positive Web controller entered route markers: {controller}",
        )
    for marker in PATHINFO_H5_MARKERS:
        require(marker in route_markers, f"required PATHINFO/H5 route marker missing: {marker}")
    parsed["DENIED_ROUTE_MARKERS"] = route_markers

    direct_view_replacements = extract_php_const_map(source, "DEFAULT_THEME_VIEW_REPLACEMENTS")
    require(
        direct_view_replacements == DEFAULT_THEME_VIEW_REPLACEMENTS,
        "DEFAULT_THEME_VIEW_REPLACEMENTS differs from the two approved direct mappings",
    )
    fallback_view_replacements = extract_php_const_map(source, "DEFAULT_FALLBACK_VIEW_REPLACEMENTS")
    require(
        fallback_view_replacements == DEFAULT_FALLBACK_VIEW_REPLACEMENTS,
        "DEFAULT_FALLBACK_VIEW_REPLACEMENTS differs from the two approved fallback mappings",
    )
    require(
        set(direct_view_replacements.values()) == set(fallback_view_replacements.values()),
        "direct and fallback mappings must resolve to the same two plugin templates",
    )
    parsed["DEFAULT_THEME_VIEW_REPLACEMENTS"] = tuple(direct_view_replacements)
    parsed["DEFAULT_FALLBACK_VIEW_REPLACEMENTS"] = tuple(fallback_view_replacements)

    replacement_method_source = extract_php_method(source, "ReplacementView")
    replacement_method = compact_code(replacement_method_source)
    require(
        re.search(
            r"\bpublic\s+static\s+function\s+ReplacementView\s*\(\s*\$view\s*,\s*\$theme\s*\)",
            source,
            flags=re.IGNORECASE,
        )
        is not None,
        "ReplacementView must remain a public static two-argument boundary",
    )
    replacement_fragments = (
        "if(!is_string($view)){return$view;}",
        r"$normalized_view=str_replace('\\','/',$view);",
        "if(isset(self::default_fallback_view_replacements[$normalized_view]))",
        "returnself::default_fallback_view_replacements[$normalized_view];",
        "if($theme==='default'&&isset(self::default_theme_view_replacements[$normalized_view]))",
        "returnself::default_theme_view_replacements[$normalized_view];",
        "return$view;",
    )
    for fragment in replacement_fragments:
        require(fragment in replacement_method, f"view replacement boundary missing: {fragment}")
    require(
        replacement_method.index("self::default_fallback_view_replacements")
        < replacement_method.index("$theme==='default'"),
        "explicit default fallbacks must be resolved before the direct-theme condition",
    )
    require(
        replacement_method_source.lower().count("str_replace(") == 1
        and source.lower().count("str_replace(") == 1,
        "backslash normalization must be the policy's only str_replace call",
    )
    for forbidden_fragment in (
        "strpos(",
        "stripos(",
        "str_contains(",
        "preg_match(",
        "preg_match_all(",
        "preg_replace(",
        "fnmatch(",
        "strtolower(",
        "trim(",
        "requestparams(",
        "requestparam(",
        "request::",
        "input(",
        "$_get",
        "$_post",
        "$_request",
    ):
        require(
            forbidden_fragment not in replacement_method,
            f"view replacement must stay exact and request-independent: {forbidden_fragment}",
        )

    request_method = compact_code(extract_php_method(source, "IsRequestDenied"))
    for token in (
        "self::normalize($module)",
        "self::normalize($controller)",
        "if($controller==='plugins')",
        "in_array($module,['index','api','admin'],true)",
        "self::isplugindenied($plugins)",
        "self::web_denied_controllers",
        "self::api_denied_controllers",
        "self::admin_denied_controllers",
        "returnfalse;",
    ):
        require(token in request_method, f"request boundary is missing fragment {token}")
    require("$action" not in request_method, "controller deny policy must not depend on action")
    require("requestaction(" not in request_method, "action lookup can create a route bypass")
    require(
        "ispluginentrydenied(" not in request_method,
        "direct request blocking must not consume the entry-only hidden set",
    )

    plugin_method = compact_code(extract_php_method(source, "IsPluginDenied"))
    require("self::normalize($plugins)" in plugin_method, "plugin identifier must be normalized")
    require("self::denied_plugins" in plugin_method, "plugin deny set must be fixed")
    require("self::denied_plugin_aliases" in plugin_method, "verified ShopXO plugin aliases must be denied")
    require(
        "self::hidden_plugin_entries" not in plugin_method,
        "entry-only identifiers must not become permanent direct route denials",
    )

    plugin_entry_method = compact_code(extract_php_method(source, "IsPluginEntryDenied"))
    for token in (
        "self::normalize($plugins)",
        "self::isplugindenied($plugins)",
        "self::hidden_plugin_entries",
    ):
        require(token in plugin_entry_method, f"entry-only plugin boundary missing: {token}")

    normalize_method = compact_code(extract_php_method(source, "Normalize"))
    require(
        "strtolower(trim((string)$value))" in normalize_method,
        "case-insensitive matching must use trim plus strtolower",
    )

    navigation_method = compact_code(extract_php_method(source, "FilterNavigation"))
    for token in (
        "foreach(['items','item','children']as$children_key)",
        "self::filternavigation(",
        "self::isnavigationitemdenied($item)",
        "self::preservelistshape(",
    ):
        require(token in navigation_method, f"recursive navigation filtering missing: {token}")

    navigation_item_method = compact_code(extract_php_method(source, "IsNavigationItemDenied"))
    for token in (
        "foreach(['control','controller']as$key)",
        "foreach(['url','value','event_value','only_tag','type']as$key)",
        "self::ispluginmenuitemdenied($item)",
        "self::containsdeniedroute(",
    ):
        require(token in navigation_item_method, f"structured navigation field missing: {token}")

    denied_route_method = compact_code(extract_php_method(source, "ContainsDeniedRoute"))
    for token in (
        "if(self::urlcontainsdeniedwebcontroller($value))",
        "if(strpos($marker,'s=')===0)",
        "preg_match('#(?:^|[?&])'.preg_quote($marker,'#').'#',$value)===1",
        "elseif(strpos($marker,'/')!==false)",
        "preg_match('#(?:^|[=/])'.preg_quote($marker,'#').'(?=/|[.?#&]|$)#',$value)===1",
        "elseif(preg_match('#^(?:index)?'.preg_quote($marker,'#').'$#',$value)===1)",
    ):
        require(token in denied_route_method, f"navigation route boundary missing: {token}")
    require(
        "strpos($value,$marker)" not in denied_route_method,
        "route markers must not fall back to substring matching",
    )

    web_controller_method = compact_code(extract_php_method(source, "UrlContainsDeniedWebController"))
    for token in (
        "parse_url($value,php_url_path)",
        "!is_string($path)||$path===''",
        "$path=trim($path,'/')",
        "$segments=explode('/',$path)",
        "$controller=$segments[0]",
        "$controller==='index'&&isset($segments[1])",
        "$controller=$segments[1]",
        "$controller=explode('.',$controller,2)[0]",
        "in_array(self::normalize($controller),self::web_denied_controllers,true)",
    ):
        require(token in web_controller_method, f"PATHINFO Web controller boundary missing: {token}")
    require(
        "api_denied_controllers" not in web_controller_method
        and "admin_denied_controllers" not in web_controller_method,
        "PATHINFO helper must only use the Web controller deny set",
    )

    plugin_menu_method = compact_code(extract_php_method(source, "IsPluginMenuItemDenied"))
    for token in (
        "foreach(['id','key']as$key)",
        "strpos($marker,'plugins-')===0",
        "substr($marker,8)",
        "self::ispluginentrydenied(substr($marker,8))",
        "foreach(['url','value','event_value']as$key)",
        "self::pluginfromurlisdenied(",
    ):
        require(token in plugin_menu_method, f"plugin menu recognition missing: {token}")

    plugin_url_method = compact_code(extract_php_method(source, "PluginFromUrlIsDenied"))
    require(
        "(?:^|[?&/])pluginsname(?:/|=)([a-z0-9_-]+)" in plugin_url_method,
        "pluginsname must have a real query/path left boundary",
    )
    require(
        "(?:^|/)pages/plugins/([a-z0-9_-]+)(?:/|[?#]|$)" in plugin_url_method,
        "ShopXO H5 plugin route boundary missing",
    )
    require(
        "preg_match_all($pattern,$value,$matches)>0" in plugin_url_method,
        "plugin URL filtering must collect every occurrence",
    )
    require(
        "foreach($matches[1]as$plugins)" in plugin_url_method,
        "plugin URL filtering must inspect every captured plugin identifier",
    )
    require(
        "self::ispluginentrydenied($plugins)" in plugin_url_method,
        "every captured plugin identifier must include the entry-only hidden set",
    )
    require(
        re.search(r"\bpreg_match\s*\(", extract_php_method(source, "PluginFromUrlIsDenied"), flags=re.IGNORECASE)
        is None,
        "single-match preg_match permits an allowed-first denied-second bypass",
    )
    normalize_url_method = compact_code(extract_php_method(source, "NormalizeUrl"))
    require("rawurldecode(" in normalize_url_method, "URL-encoded plugin names must be normalized")
    require("html_entity_decode(" in normalize_url_method, "HTML-encoded query strings must be normalized")

    admin_menu_method = compact_code(extract_php_method(source, "FilterAdminMenu"))
    for token in (
        "self::filteradminmenu(",
        "self::admin_denied_controllers",
        "self::ispluginmenuitemdenied($item)",
        "self::preservelistshape(",
    ):
        require(token in admin_menu_method, f"admin_left_menu filtering missing: {token}")

    admin_power_method = compact_code(extract_php_method(source, "FilterAdminPower"))
    for token in ("self::admin_denied_controllers", "unset($data[$key])"):
        require(token in admin_power_method, f"admin_power filtering missing: {token}")
    require(
        "strpos($normalized,$control.'_')===0" in admin_power_method,
        "admin_power must filter by exact controller key prefix",
    )

    plugin_map_method = compact_code(extract_php_method(source, "FilterPluginMap"))
    for token in ("$item['plugins']", "self::ispluginentrydenied($plugins)", "unset($data[$key])"):
        require(token in plugin_map_method, f"admin plugin map filtering missing: {token}")

    button_method = compact_code(extract_php_method(source, "FilterGoodsButtons"))
    for token in (
        "array_values(array_filter(",
        "$item['type']",
        "return!in_array($type,['buy','cart'],true)",
    ):
        require(token in button_method, f"goods button contract missing: {token}")

    shortcut_method = compact_code(extract_php_method(source, "FilterShortcutMenu"))
    for token in (
        "$item['menu']",
        "$item['url']",
        "($menu!==''&&$url==='')",
        "strpos($menu,'plugins-')===0",
        "self::ispluginentrydenied(substr($menu,8))",
        "self::isnavigationitemdenied($item)",
        "self::urlcontainsdeniedadmincontroller($url)",
        "self::preservelistshape($data,$result)",
    ):
        require(token in shortcut_method, f"shortcut_menu_data filtering missing: {token}")

    shortcut_admin_url_method = compact_code(extract_php_method(source, "UrlContainsDeniedAdminController"))
    for token in (
        "self::normalizeurl($value)",
        "self::admin_denied_controllers",
        "$controller=preg_quote($controller,'#')",
        "preg_match('#(?:^|[?&])s='.$controller.'/#',$value)===1",
        "preg_match('#(?:^|/)admin/'.$controller.'/#',$value)===1",
    ):
        require(token in shortcut_admin_url_method, f"shortcut admin URL boundary missing: {token}")
    require("strpos(" not in shortcut_admin_url_method, "admin shortcut matching must not use substring checks")

    lowered = source.lower()
    for forbidden in (
        "$_get",
        "$_post",
        "$_request",
        "requestparams(",
        "input(",
        "array_merge(",
        "db::",
        "config/shopxo.sql",
        "file_get_contents(",
        "preg_replace(",
    ):
        require(forbidden not in lowered, f"policy must not use dynamic/core shortcut: {forbidden}")
    return parsed


def validate_policy_file(path: Path) -> dict[str, tuple[str, ...]]:
    return validate_policy_source(read_utf8(path))


def validate_hook_source(source: str) -> None:
    navigation_hooks = extract_php_const_list(source, "NAVIGATION_HOOKS")
    require(navigation_hooks == NAVIGATION_HOOKS, "Hook NAVIGATION_HOOKS differs from approved hooks")
    hook_literals = set(
        re.findall(r"['\"](plugins_(?:service|view)_[a-z0-9_]+)['\"]", source, flags=re.IGNORECASE)
    )
    require(hook_literals == set(EXPECTED_HOOKS), "Hook dispatcher handles an incomplete or widened hook set")

    handle_method = compact_code(extract_php_method(source, "handle"))
    for token in (
        "$params['hook_name']",
        "self::navigation_hooks",
        "scopepolicy::filternavigation($params['data'])",
        "scopepolicy::filtergoodsbuttons($params['data'])",
        "$this->filteradminscope($params)",
        "$this->filterassignedviewdata($params)",
        "$this->replacerestrictedview($params)",
        "returnnull;",
    ):
        require(token in handle_method, f"Hook dispatcher missing: {token}")

    enforce_method = extract_php_method(source, "EnforceRequestScope")
    compact_enforce = compact_code(enforce_method)
    for token in (
        "$module=requestmodule();",
        "$controller=requestcontroller();",
        "$plugins=(strtolower($controller)==='plugins')?pluginsrequestname():'';",
        "scopepolicy::isrequestdenied($module,$controller,$plugins)",
    ):
        require(token in compact_enforce, f"system-begin request guard missing: {token}")
    require("requestaction(" not in compact_enforce, "denied controller must cover every action")
    require(
        len(re.findall(r"\babort\s*\(\s*404\s*,", enforce_method, flags=re.IGNORECASE)) == 1,
        "denied request must abort exactly once with HTTP 404",
    )
    require("datareturn(" not in compact_enforce, "return arrays cannot replace abort semantics")

    admin_method = compact_code(extract_php_method(source, "FilterAdminScope"))
    admin_filters = {
        "admin_left_menu": "filteradminmenu",
        "admin_power": "filteradminpower",
        "admin_plugins": "filterpluginmap",
        "admin_all_plugins": "filterpluginmap",
    }
    for key, method in admin_filters.items():
        require(f"isset($params['{key}'])" in admin_method, f"admin payload key not guarded: {key}")
        require(
            f"$params['{key}']=scopepolicy::{method}($params['{key}'])" in admin_method,
            f"admin payload key not filtered: {key}",
        )

    assigned_method = compact_code(extract_php_method(source, "FilterAssignedViewData"))
    for token in (
        "!isset($params['data'])||!is_array($params['data'])",
        "$module=strtolower(requestmodule());",
        "$controller=strtolower(requestcontroller());",
        "$action=strtolower(requestaction());",
        "if($module==='index'&&$controller==='index'&&$action==='index')",
        "unset($params['data']['user_order_status'])",
        "elseif($module==='admin'&&$controller==='index'&&$action==='init'",
        "isset($params['data']['shortcut_menu_data'])",
        "$params['data']['shortcut_menu_data']=scopepolicy::filtershortcutmenu($params['data']['shortcut_menu_data'])",
    ):
        require(token in assigned_method, f"view-assignment filtering missing: {token}")

    view_method_source = extract_php_method(source, "ReplaceRestrictedView")
    view_method = compact_code(view_method_source)
    for token in (
        "if(requestmodule()!=='index'||!array_key_exists('view',$params)){return;}",
        "if(requestcontroller()==='user'&&requestaction()==='index')",
        "array_key_exists('view',$params)",
        "$params['view']='../../../plugins/nursery/view/index/user/index';",
        "$params['view']=scopepolicy::replacementview($params['view'],defaulttheme());",
    ):
        require(token in view_method, f"restricted view replacement missing: {token}")
    user_view_assignment = "$params['view']='../../../plugins/nursery/view/index/user/index';"
    policy_view_assignment = "$params['view']=scopepolicy::replacementview($params['view'],defaulttheme());"
    user_return = view_method.find("return;", view_method.index(user_view_assignment))
    require(
        view_method.index(user_view_assignment) < user_return < view_method.index(policy_view_assignment),
        "user-center replacement must return before the goods-view mapping",
    )
    require(
        len(re.findall(r"\bDefaultTheme\s*\(\s*\)", view_method_source, flags=re.IGNORECASE)) == 1,
        "goods-view mapping must consult DefaultTheme exactly once",
    )

    lowered = source.lower()
    for forbidden in ("str_replace(", "preg_replace(", "db::", "config/shopxo.sql"):
        require(forbidden not in lowered, f"Hook uses forbidden rendered/core shortcut: {forbidden}")


def validate_hook_file(path: Path) -> None:
    validate_hook_source(read_utf8(path))


def validate_event_source(source: str) -> None:
    methods = tuple(re.findall(r"\bpublic\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", source))
    require(methods == EXPECTED_EVENT_METHODS, "Event lifecycle callbacks changed")
    for method in EXPECTED_EVENT_METHODS:
        body = compact_code(extract_php_method(source, method))
        require("return datareturn('success',0);".replace(" ", "") in body, f"{method} must be a no-op success callback")
    lowered = source.lower()
    for forbidden in ("db::", "->execute(", "->query(", "config/shopxo.sql", "app\\service\\"):
        require(forbidden not in lowered, f"Event lifecycle must not mutate data/core: {forbidden}")


def validate_view_source(source: str) -> None:
    lowered = source.lower()
    for include in (
        "public/header",
        "public/nav",
        "public/header_top_nav",
        "public/header_nav_simple",
        "public/user_menu",
        "public/footer",
    ):
        require(
            re.search(rf"moduleinclude\(\s*['\"]{re.escape(include)}['\"]", source, flags=re.IGNORECASE)
            is not None,
            f"user center lost shared module: {include}",
        )

    for route in (
        "index/personal/index",
        "index/safety/index",
        "index/message/index",
        "index/usergoodsfavor/index",
        "index/usergoodsbrowse/index",
        "index/goods/index",
    ):
        require(route in lowered, f"positive user-center route missing: {route}")
    for token in ("goods_favor_list", "goods_browse_list", "mini_navigation", "user.avatar", "user.user_name_view"):
        require(token in lowered, f"positive user-center data missing: {token}")
    for hook in EXPECTED_USER_VIEW_HOOKS:
        require(hook in lowered, f"upstream user-center extension point missing: {hook}")

    for controller in WEB_DENIED:
        patterns = (
            rf"(?:^|[^a-z0-9_])index/{re.escape(controller)}/",
            rf"(?:^|[^a-z0-9_]){re.escape(controller)}/index(?:[^a-z0-9_]|$)",
            rf"[?&]s={re.escape(controller)}(?:/|&|['\"]|$)",
            rf"(?:^|[^a-z0-9_]){re.escape(controller)}index(?:[^a-z0-9_]|$)",
        )
        for pattern in patterns:
            require(
                re.search(pattern, lowered, flags=re.IGNORECASE) is None,
                f"forbidden user-center route remains: {controller}",
            )

    for token in ("order_list", "cart_list", "user_order_status", "display:none", "display: none"):
        require(token not in lowered, f"transaction block or CSS hiding remains in user center: {token}")
    require("inquiry" not in lowered and "询价" not in source, "task must not add a fake inquiry entry")

    plugin_pattern = re.compile(
        r"(?:^|[?&/])pluginsname(?:/|=)([a-z0-9_-]+)|(?:^|/)pages/plugins/([a-z0-9_-]+)(?:/|[?#]|$)"
    )
    for match in plugin_pattern.finditer(lowered):
        plugin = match.group(1) or match.group(2)
        require(not model_is_plugin_entry_denied(plugin), f"hidden or PX plugin URL remains in user center: {plugin}")

    require(
        len(re.findall(r"\{\{\s*if\b", lowered)) == lowered.count("{{/if}}"),
        "unbalanced user-center if blocks",
    )
    require(
        len(re.findall(r"\{\{\s*foreach\b", lowered)) == lowered.count("{{/foreach}}"),
        "unbalanced user-center foreach blocks",
    )


def validate_view_file(path: Path) -> None:
    validate_view_source(read_utf8(path))


def controlled_goods_view_transform(upstream_source: str, cart_node: str, label: str) -> str:
    normalized_upstream = normalize_newlines(upstream_source)
    require(
        normalized_upstream.count(cart_node) == 1,
        f"pinned upstream {label} template must contain the approved cart node exactly once",
    )
    return normalized_upstream.replace(cart_node, "", 1)


def validate_goods_view_source(
    source: str,
    upstream_source: str,
    cart_node: str,
    label: str,
) -> None:
    normalized_source = normalize_newlines(source)
    normalized_upstream = normalize_newlines(upstream_source)
    expected_source = controlled_goods_view_transform(normalized_upstream, cart_node, label)
    require(
        normalized_source == expected_source,
        f"nursery {label} template must equal pinned upstream with only its approved cart node removed",
    )

    lowered = normalized_source.lower()
    for forbidden_marker in FORBIDDEN_GOODS_CART_MARKERS:
        require(forbidden_marker not in lowered, f"nursery {label} template retains cart marker: {forbidden_marker}")

    for price_fragment in (
        "show_price_symbol",
        "show_price_unit",
        '<strong class="price">',
    ):
        require(
            normalized_source.count(price_fragment) == normalized_upstream.count(price_fragment) > 0,
            f"nursery {label} template changed public price/unit output: {price_fragment}",
        )
    require(
        normalized_source.count("goods_url") == normalized_upstream.count("goods_url") > 0,
        f"nursery {label} template changed goods_url links",
    )
    for hook_name in EXPECTED_GOODS_VIEW_HOOKS:
        require(
            normalized_source.count(hook_name) == normalized_upstream.count(hook_name) > 0,
            f"nursery {label} template changed upstream Hook: {hook_name}",
        )


def validate_goods_view_file(
    path: Path,
    upstream_path: Path,
    cart_node: str,
    label: str,
) -> None:
    validate_goods_view_source(read_utf8(path), read_utf8(upstream_path), cart_node, label)


def model_replacement_view(view: Any, theme: Any) -> Any:
    if not isinstance(view, str):
        return view
    normalized_view = view.replace("\\", "/")
    if normalized_view in DEFAULT_FALLBACK_VIEW_REPLACEMENTS:
        return DEFAULT_FALLBACK_VIEW_REPLACEMENTS[normalized_view]
    if theme == "default" and normalized_view in DEFAULT_THEME_VIEW_REPLACEMENTS:
        return DEFAULT_THEME_VIEW_REPLACEMENTS[normalized_view]
    return view


def model_is_request_denied(module: Any, controller: Any, plugins: Any = "", action: Any = "index") -> bool:
    del action
    normalized_module = str(module).strip().lower()
    normalized_controller = str(controller).strip().lower()
    if normalized_controller == "plugins":
        return normalized_module in {"index", "api", "admin"} and model_is_plugin_denied(plugins)
    policies = {
        "index": set(WEB_DENIED),
        "api": set(API_DENIED),
        "admin": set(ADMIN_DENIED),
    }
    return normalized_controller in policies.get(normalized_module, set())


def _normalized_url(value: Any) -> str:
    return unquote(html.unescape(str(value))).strip().lower()


def model_is_plugin_denied(plugin: Any) -> bool:
    normalized = str(plugin).strip().lower()
    return normalized in set(PX_PLUGINS) | set(PX_PLUGIN_ALIASES)


def model_is_plugin_entry_denied(plugin: Any) -> bool:
    normalized = str(plugin).strip().lower()
    return model_is_plugin_denied(normalized) or normalized in set(HIDDEN_PLUGIN_ENTRIES)


def _plugin_names_from_url(value: Any) -> tuple[str, ...]:
    normalized = _normalized_url(value)
    patterns = (
        r"(?:^|[?&/])pluginsname(?:/|=)([a-z0-9_-]+)",
        r"(?:^|/)pages/plugins/([a-z0-9_-]+)(?:/|[?#]|$)",
    )
    result: list[str] = []
    for pattern in patterns:
        result.extend(match.group(1) for match in re.finditer(pattern, normalized))
    return tuple(result)


def model_plugin_menu_item_denied(item: Mapping[str, Any]) -> bool:
    for key in ("id", "key"):
        marker = str(item.get(key, "")).strip().lower()
        if marker.startswith("plugins-") and model_is_plugin_entry_denied(marker[8:]):
            return True
    for key in ("url", "value", "event_value"):
        if any(model_is_plugin_entry_denied(plugin) for plugin in _plugin_names_from_url(item.get(key, ""))):
            return True
    return False


def model_url_contains_denied_web_controller(value: Any) -> bool:
    normalized = _normalized_url(value)
    try:
        path = urlsplit(normalized).path.strip("/")
    except ValueError:
        return False
    if not path:
        return False
    segments = path.split("/")
    controller = segments[0]
    if controller == "index" and len(segments) > 1:
        controller = segments[1]
    controller = controller.split(".", 1)[0].strip().lower()
    return controller in set(WEB_DENIED)


def model_contains_denied_route(value: Any, route_markers: Sequence[str]) -> bool:
    normalized = _normalized_url(value)
    if model_url_contains_denied_web_controller(normalized):
        return True
    for marker in route_markers:
        escaped = re.escape(marker)
        if marker.startswith("s="):
            if re.search(rf"(?:^|[?&]){escaped}", normalized) is not None:
                return True
        elif "/" in marker:
            if re.search(rf"(?:^|[=/]){escaped}(?=/|[.?#&]|$)", normalized) is not None:
                return True
        elif re.fullmatch(rf"(?:index)?{escaped}", normalized) is not None:
            return True
    return False


def model_navigation_item_denied(item: Mapping[str, Any], route_markers: Sequence[str]) -> bool:
    for key in ("control", "controller"):
        control = str(item.get(key, "")).strip().lower()
        if control in set(WEB_DENIED) | set(API_DENIED):
            return True
    if model_plugin_menu_item_denied(item):
        return True
    for key in ("url", "value", "event_value", "only_tag", "type"):
        if model_contains_denied_route(item.get(key, ""), route_markers):
            return True
    return False


def model_filter_goods_buttons(items: Sequence[Any]) -> list[Any]:
    result: list[Any] = []
    for item in items:
        if isinstance(item, Mapping) and str(item.get("type", "")).strip().lower() in {"buy", "cart"}:
            continue
        result.append(item)
    return result


def model_url_contains_denied_admin_controller(value: Any) -> bool:
    normalized = _normalized_url(value)
    return any(
        re.search(rf"(?:^|[?&])s={re.escape(controller)}/", normalized) is not None
        or re.search(rf"(?:^|/)admin/{re.escape(controller)}/", normalized) is not None
        for controller in ADMIN_DENIED
    )


def model_filter_shortcut_menu(items: Sequence[Any], route_markers: Sequence[str]) -> list[Any]:
    result: list[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            result.append(item)
            continue
        raw_menu = item.get("menu", "")
        raw_url = item.get("url", "")
        menu = str(raw_menu).strip().lower() if isinstance(raw_menu, (str, int, float, bool)) else ""
        url = str(raw_url).strip() if isinstance(raw_url, (str, int, float, bool)) else ""
        if menu and not url:
            continue
        if menu.startswith("plugins-") and model_is_plugin_entry_denied(menu[8:]):
            continue
        if model_navigation_item_denied(item, route_markers) or model_url_contains_denied_admin_controller(url):
            continue
        result.append(item)
    return result


class ManifestContractTests(unittest.TestCase):
    def test_manifest_registers_exact_shopxo_hooks(self) -> None:
        config = validate_manifest_file(CONFIG_FILE)
        self.assertEqual(len(config["hook"]), 15)

    def test_removing_any_hook_fails_on_temporary_copy(self) -> None:
        original = validate_manifest_file(CONFIG_FILE)
        for hook_name in EXPECTED_HOOKS:
            with self.subTest(hook=hook_name):
                mutated = deepcopy(original)
                del mutated["hook"][hook_name]
                content = json.dumps(mutated, ensure_ascii=False, indent=2)
                with temporary_copy(CONFIG_FILE, content) as path:
                    with self.assertRaises(ContractError):
                        validate_manifest_file(path)


class ScopePolicyContractTests(unittest.TestCase):
    def test_fixed_denied_and_positive_sets(self) -> None:
        parsed = validate_policy_file(POLICY_FILE)
        self.assertEqual(len(parsed["WEB_DENIED_CONTROLLERS"]), 8)
        self.assertEqual(len(parsed["API_DENIED_CONTROLLERS"]), 10)
        self.assertEqual(len(parsed["ADMIN_DENIED_CONTROLLERS"]), 12)
        self.assertEqual(len(parsed["DENIED_PLUGINS"]), 23)
        self.assertEqual(len(parsed["DENIED_PLUGIN_ALIASES"]), 4)
        self.assertEqual(len(parsed["HIDDEN_PLUGIN_ENTRIES"]), 8)
        self.assertEqual(len(parsed["DEFAULT_THEME_VIEW_REPLACEMENTS"]), 2)
        self.assertEqual(len(parsed["DEFAULT_FALLBACK_VIEW_REPLACEMENTS"]), 2)

    def test_exact_goods_view_mappings_and_theme_model(self) -> None:
        validate_policy_file(POLICY_FILE)
        for view, replacement in DEFAULT_THEME_VIEW_REPLACEMENTS.items():
            with self.subTest(mapping="direct-default", view=view):
                self.assertEqual(model_replacement_view(view, "default"), replacement)
                self.assertEqual(model_replacement_view(view.replace("/", "\\"), "default"), replacement)
            for theme in ("nursery", "Default", "DEFAULT", "", None):
                with self.subTest(mapping="direct-custom", view=view, theme=theme):
                    self.assertEqual(model_replacement_view(view, theme), view)
                    windows_view = view.replace("/", "\\")
                    self.assertEqual(model_replacement_view(windows_view, theme), windows_view)

        for view, replacement in DEFAULT_FALLBACK_VIEW_REPLACEMENTS.items():
            for theme in ("default", "nursery", "Default", "DEFAULT", "", None):
                with self.subTest(mapping="fallback", view=view, theme=theme):
                    self.assertEqual(model_replacement_view(view, theme), replacement)
                    self.assertEqual(model_replacement_view(view.replace("/", "\\"), theme), replacement)

        similar_or_case_changed = (
            "module/goods/list/base.html",
            "module/goods/list/base/",
            "/module/goods/list/base",
            "module//goods/list/base",
            "module/goods/list/basement",
            "prefix/module/goods/list/base",
            "MODULE/goods/list/base",
            "module/goods/slider/binding.html",
            "module/goods/slider/binding-extra",
            "../default/module/goods/list/base.html",
            "../defaulted/module/goods/list/base",
            "../DEFAULT/module/goods/list/base",
            "../../default/module/goods/slider/binding",
        )
        for view in similar_or_case_changed:
            for theme in ("default", "nursery"):
                with self.subTest(mapping="exact-negative", view=view, theme=theme):
                    self.assertEqual(model_replacement_view(view, theme), view)
        for opaque_view in (None, 7, False, ("module/goods/list/base",)):
            with self.subTest(mapping="non-string", view=opaque_view):
                self.assertIs(model_replacement_view(opaque_view, "default"), opaque_view)

    def test_goods_view_mapping_mutations_fail_on_temporary_copy(self) -> None:
        source = read_utf8(POLICY_FILE)
        mutations: list[tuple[str, str]] = []
        for const_name, mappings in (
            ("DEFAULT_THEME_VIEW_REPLACEMENTS", DEFAULT_THEME_VIEW_REPLACEMENTS),
            ("DEFAULT_FALLBACK_VIEW_REPLACEMENTS", DEFAULT_FALLBACK_VIEW_REPLACEMENTS),
        ):
            for view in mappings:
                mutations.append(
                    (
                        f"remove {const_name} {view}",
                        mutate_const_remove_map_entry(source, const_name, view),
                    )
                )

        mutations.extend(
            (
                (
                    "remove strict default condition",
                    mutate_method_once(
                        source,
                        "ReplacementView",
                        "if($theme === 'default' && isset(self::DEFAULT_THEME_VIEW_REPLACEMENTS[$normalized_view]))",
                        "if(isset(self::DEFAULT_THEME_VIEW_REPLACEMENTS[$normalized_view]))",
                        "strict default theme condition",
                    ),
                ),
                (
                    "replace custom theme direct path",
                    mutate_method_once(
                        source,
                        "ReplacementView",
                        "$theme === 'default'",
                        "$theme !== 'default'",
                        "custom theme direct replacement",
                    ),
                ),
                (
                    "do not replace explicit fallback",
                    mutate_method_once(
                        source,
                        "ReplacementView",
                        "return self::DEFAULT_FALLBACK_VIEW_REPLACEMENTS[$normalized_view];",
                        "return $view;",
                        "fallback replacement return",
                    ),
                ),
                (
                    "downgrade exact map lookup to substring",
                    mutate_method_once(
                        source,
                        "ReplacementView",
                        "isset(self::DEFAULT_FALLBACK_VIEW_REPLACEMENTS[$normalized_view])",
                        "strpos($normalized_view, '../default/module/goods/list/base') !== false",
                        "fallback exact mapping",
                    ),
                ),
                (
                    "downgrade exact map lookup to regex",
                    mutate_method_once(
                        source,
                        "ReplacementView",
                        "isset(self::DEFAULT_THEME_VIEW_REPLACEMENTS[$normalized_view])",
                        "preg_match('#module/goods/#', $normalized_view) === 1",
                        "direct exact mapping",
                    ),
                ),
                (
                    "source replacement view from request input",
                    mutate_method_once(
                        source,
                        "ReplacementView",
                        "$normalized_view = str_replace('\\\\', '/', $view);",
                        "$normalized_view = str_replace('\\\\', '/', $_GET['view']);",
                        "request-independent view input",
                    ),
                ),
            )
        )
        for label, mutated in mutations:
            with self.subTest(mutation=label):
                with temporary_copy(POLICY_FILE, mutated) as path:
                    with self.assertRaises(ContractError):
                        validate_policy_file(path)

    def test_controller_level_case_insensitive_route_model(self) -> None:
        denied_by_module = {
            "index": WEB_DENIED,
            "api": API_DENIED,
            "admin": ADMIN_DENIED,
        }
        for module, controllers in denied_by_module.items():
            for controller in controllers:
                for action in ("index", "save", "delete", "ArBiTrArY"):
                    with self.subTest(module=module, controller=controller, action=action):
                        self.assertTrue(model_is_request_denied(module.upper(), controller.upper(), action=action))

        allowed_by_module = {
            "index": WEB_ALLOWED,
            "api": API_ALLOWED,
            "admin": ADMIN_ALLOWED,
        }
        for module, controllers in allowed_by_module.items():
            for controller in controllers:
                with self.subTest(module=module, controller=controller):
                    self.assertFalse(model_is_request_denied(module, controller))

        for plugin in PX_PLUGINS:
            for module in ("index", "api", "admin"):
                with self.subTest(module=module, plugin=plugin):
                    self.assertTrue(model_is_request_denied(module, "PlUgInS", plugin.upper()))
            self.assertFalse(model_is_request_denied("index", "goods", plugin))
        for plugin in PX_PLUGIN_ALIASES:
            for module in ("index", "api", "admin"):
                with self.subTest(module=module, plugin_alias=plugin):
                    self.assertTrue(model_is_request_denied(module, "PlUgInS", plugin.upper()))
        for plugin in HIDDEN_PLUGIN_ENTRIES:
            for module in ("index", "api", "admin"):
                with self.subTest(module=module, entry_only=plugin):
                    self.assertFalse(model_is_request_denied(module, "PlUgInS", plugin.upper()))
                    self.assertTrue(model_is_plugin_entry_denied(plugin.upper()))
        self.assertFalse(model_is_request_denied("install", "cart"))
        self.assertFalse(model_is_request_denied("index", "plugins", "nursery"))

    def test_removing_any_fixed_denied_literal_fails_on_temporary_copy(self) -> None:
        source = read_utf8(POLICY_FILE)
        for const_name, values in (
            ("WEB_DENIED_CONTROLLERS", WEB_DENIED),
            ("API_DENIED_CONTROLLERS", API_DENIED),
            ("ADMIN_DENIED_CONTROLLERS", ADMIN_DENIED),
            ("DENIED_PLUGINS", PX_PLUGINS),
            ("DENIED_PLUGIN_ALIASES", PX_PLUGIN_ALIASES),
            ("HIDDEN_PLUGIN_ENTRIES", HIDDEN_PLUGIN_ENTRIES),
            ("DENIED_ROUTE_MARKERS", PATHINFO_H5_MARKERS),
        ):
            for value in values:
                with self.subTest(constant=const_name, value=value):
                    mutated = mutate_const_remove_item(source, const_name, value)
                    with temporary_copy(POLICY_FILE, mutated) as path:
                        with self.assertRaises(ContractError):
                            validate_policy_file(path)

    def test_direct_deny_and_entry_only_branch_mutations_fail(self) -> None:
        source = read_utf8(POLICY_FILE)
        mutations = (
            mutate_method_once(
                source,
                "IsPluginDenied",
                "return in_array($plugins, self::DENIED_PLUGINS, true) || in_array($plugins, self::DENIED_PLUGIN_ALIASES, true);",
                "return in_array($plugins, self::DENIED_PLUGINS, true) || in_array($plugins, self::DENIED_PLUGIN_ALIASES, true) || in_array($plugins, self::HIDDEN_PLUGIN_ENTRIES, true);",
                "entry-only identifier promoted to direct deny",
            ),
            mutate_method_once(
                source,
                "IsPluginEntryDenied",
                "self::IsPluginDenied($plugins)",
                "false",
                "direct deny omitted from entry deny",
            ),
            mutate_method_once(
                source,
                "IsPluginMenuItemDenied",
                "self::IsPluginEntryDenied(substr($marker, 8))",
                "self::IsPluginDenied(substr($marker, 8))",
                "entry-only id/key menu branch",
            ),
            mutate_method_once(
                source,
                "PluginFromUrlIsDenied",
                "self::IsPluginEntryDenied($plugins)",
                "self::IsPluginDenied($plugins)",
                "entry-only plugin URL branch",
            ),
            mutate_method_once(
                source,
                "FilterPluginMap",
                "self::IsPluginEntryDenied($plugins)",
                "self::IsPluginDenied($plugins)",
                "entry-only admin plugin map branch",
            ),
        )
        for index, mutated in enumerate(mutations):
            with self.subTest(mutation=index):
                with temporary_copy(POLICY_FILE, mutated) as path:
                    with self.assertRaises(ContractError):
                        validate_policy_file(path)

    def test_each_direct_or_entry_only_plugin_menu_shape_is_rejected(self) -> None:
        for plugin in PX_PLUGINS + PX_PLUGIN_ALIASES + HIDDEN_PLUGIN_ENTRIES:
            variants = (
                {"id": f"plugins-{plugin.upper()}"},
                {"key": f"Plugins-{plugin}"},
                {"url": f"/admin/pluginsadmin/index/pluginsname/{plugin}"},
                {"url": f"/admin/plugins/index?foo=1&amp;pluginsname={plugin.upper()}"},
                {"event_value": f"/api/plugins/index/pluginsname={plugin}"},
                {"event_value": f"/pages/plugins/{plugin.upper()}/index/index"},
            )
            for item in variants:
                with self.subTest(plugin_entry=plugin, item=item):
                    self.assertNotIn("control", item)
                    self.assertTrue(model_plugin_menu_item_denied(item))

        positive_items = (
            {"id": "plugins-nursery"},
            {"key": "plugins-nursery"},
            {"url": "/admin/pluginsadmin/index/pluginsname/nursery"},
            {"url": "/admin/plugins/index?pluginsname=unapproved-but-not-px"},
            {"event_value": "/pages/plugins/nursery/index/index"},
            {"event_value": "/pages/plugins/unapproved-but-not-px/index/index"},
        )
        for item in positive_items:
            self.assertFalse(model_plugin_menu_item_denied(item))

    def test_multi_plugin_urls_scan_allowed_and_denied_matches(self) -> None:
        cases = (
            (
                "?pluginsname=nursery&pluginsname=coupon",
                ("nursery", "coupon"),
                True,
            ),
            (
                "/pages/plugins/blog/x/pages/plugins/wallet/y",
                ("blog", "wallet"),
                True,
            ),
            (
                "/pages/plugins/nursery/x/pages/plugins/wallet/y",
                ("nursery", "wallet"),
                True,
            ),
            (
                "?pluginsname=nursery&pluginsname=unknownextension",
                ("nursery", "unknownextension"),
                False,
            ),
            (
                "/pages/plugins/nursery/x/pages/plugins/unknownextension/y",
                ("nursery", "unknownextension"),
                False,
            ),
            (
                "/index/goods/index?notpluginsname=coupon",
                (),
                False,
            ),
            (
                "?return_pluginsname=wallet",
                (),
                False,
            ),
            (
                "?pluginsname=coupon",
                ("coupon",),
                True,
            ),
            (
                "/pluginsname/coupon",
                ("coupon",),
                True,
            ),
        )
        for value, expected_names, expected_denied in cases:
            with self.subTest(value=value):
                self.assertEqual(_plugin_names_from_url(value), expected_names)
                self.assertEqual(model_plugin_menu_item_denied({"url": value}), expected_denied)

    def test_removing_id_key_or_url_plugin_recognition_fails(self) -> None:
        source = read_utf8(POLICY_FILE)
        mutations = (
            mutate_method_once(
                source,
                "IsPluginMenuItemDenied",
                "foreach(['id', 'key'] as $key)",
                "foreach(['key'] as $key)",
                "plugin menu id branch",
            ),
            mutate_method_once(
                source,
                "IsPluginMenuItemDenied",
                "foreach(['id', 'key'] as $key)",
                "foreach(['id'] as $key)",
                "plugin menu key branch",
            ),
            mutate_method_once(
                source,
                "IsPluginMenuItemDenied",
                "foreach(['url', 'value', 'event_value'] as $key)",
                "foreach(['value', 'event_value'] as $key)",
                "plugin menu URL branch",
            ),
            mutate_method_once(
                source,
                "PluginFromUrlIsDenied",
                "pluginsname(?:/|=)",
                "plugin(?:/|=)",
                "pluginsname URL parser",
            ),
            mutate_method_once(
                source,
                "PluginFromUrlIsDenied",
                "(?:^|[?&/])pluginsname",
                "pluginsname",
                "pluginsname left boundary",
            ),
            mutate_method_once(
                source,
                "PluginFromUrlIsDenied",
                "(?:^|/)pages/plugins/",
                "(?:^|/)pages/extensions/",
                "H5 plugin URL parser",
            ),
            mutate_method_once(
                source,
                "PluginFromUrlIsDenied",
                "preg_match_all($pattern, $value, $matches)",
                "preg_match($pattern, $value, $matches)",
                "all-match parser downgraded to first match",
            ),
            mutate_method_once(
                source,
                "PluginFromUrlIsDenied",
                "foreach($matches[1] as $plugins)",
                "foreach([$matches[1][0]] as $plugins)",
                "only first captured plugin inspected",
            ),
        )
        for index, mutated in enumerate(mutations):
            with self.subTest(mutation=index):
                with temporary_copy(POLICY_FILE, mutated) as path:
                    with self.assertRaises(ContractError):
                        validate_policy_file(path)

    def test_structured_navigation_and_button_models(self) -> None:
        parsed = validate_policy_file(POLICY_FILE)
        markers = parsed["DENIED_ROUTE_MARKERS"]
        field_values = {
            "control": "CaRt",
            "controller": "OrDeR",
            "url": "/index/cart/index",
            "value": "?s=order/index",
            "event_value": "/index/pay/index",
            "only_tag": "cartindex",
            "type": "buyindex",
        }
        for field, value in field_values.items():
            with self.subTest(field=field):
                self.assertTrue(model_navigation_item_denied({field: value}, markers))
        self.assertFalse(model_navigation_item_denied({"url": "/index/goods/index", "type": "show"}, markers))

        allowed_similar_routes = (
            ("only_tag", "preorderindex"),
            ("type", "cartindexv2"),
            ("url", "/index/cartoon/index"),
            ("url", "/pages/cartography/cartography"),
            ("url", "/pages/user-orderly/x"),
            ("url", "https://cart.example.com/"),
            ("url", "/cartoon/index.html"),
            ("url", "/order-guide/index.html"),
            ("url", "/pages/cart-info/x"),
        )
        for field, value in allowed_similar_routes:
            with self.subTest(allowed_similar=value):
                self.assertFalse(model_navigation_item_denied({field: value}, markers))

        denied_exact_routes = (
            ("only_tag", "cartindex"),
            ("type", "indexcartindex"),
            ("url", "/index/cart/index"),
            ("url", "?path=pages/user-order/x"),
            ("url", "?s=order/index"),
            ("url", "/pages/cart-page/cart-page"),
            ("url", "/pages/user-order-history/x"),
            ("url", "/cart/index.html"),
            ("url", "https://host/order/index.html"),
            ("url", "/cart.html"),
            ("url", "/buy.html"),
            ("url", "/pages/user-goods-comments/index/index"),
            ("url", "/pages/paylog-list/index/index"),
        )
        for field, value in denied_exact_routes:
            with self.subTest(denied_exact=value):
                self.assertTrue(model_navigation_item_denied({field: value}, markers))

        buttons = [
            {"type": "buy", "name": "buy"},
            {"type": "CART", "name": "cart"},
            {"type": "show", "name": "phone"},
            {"type": "inquiry", "name": "future"},
            {"type": "extension", "name": "unknown"},
            "opaque-extension",
        ]
        filtered = model_filter_goods_buttons(buttons)
        self.assertEqual(
            filtered,
            [
                {"type": "show", "name": "phone"},
                {"type": "inquiry", "name": "future"},
                {"type": "extension", "name": "unknown"},
                "opaque-extension",
            ],
        )

    def test_admin_shortcut_menu_defaults_denied_urls_and_positive_items(self) -> None:
        markers = validate_policy_file(POLICY_FILE)["DENIED_ROUTE_MARKERS"]
        shortcuts = [
            {"menu": 178, "url": ""},
            {"menu": 364},
            {"menu": "plugins-distribution", "url": "/admin/plugins/index/pluginsname/distribution"},
            {"menu": "plugins-coupon", "url": "/pages/plugins/coupon/index/index"},
            {"menu": "custom-seckill", "url": "/admin/plugins/index?pluginsname=seckill"},
            {"menu": "payment", "url": "?s=payment/index"},
            {"menu": "refund", "url": "/admin/refundlog/index"},
            {"menu": "xs-order", "url": "?xs=order/index"},
            {"menu": "return-payment", "url": "?return_s=payment/index"},
            {"menu": "goods", "url": "?s=goods/index"},
            {"menu": "site", "url": "/admin/site/index"},
            {"menu": "plugins-nursery", "url": "/admin/plugins/index?pluginsname=nursery"},
            {"menu": "", "url": ""},
            "opaque-extension",
        ]
        self.assertEqual(
            model_filter_shortcut_menu(shortcuts, markers),
            [
                {"menu": "xs-order", "url": "?xs=order/index"},
                {"menu": "return-payment", "url": "?return_s=payment/index"},
                {"menu": "goods", "url": "?s=goods/index"},
                {"menu": "site", "url": "/admin/site/index"},
                {"menu": "plugins-nursery", "url": "/admin/plugins/index?pluginsname=nursery"},
                {"menu": "", "url": ""},
                "opaque-extension",
            ],
        )

    def test_shortcut_menu_critical_branch_mutations_fail(self) -> None:
        source = read_utf8(POLICY_FILE)
        mutations = (
            mutate_method_once(
                source,
                "FilterShortcutMenu",
                "($menu !== '' && $url === '')",
                "false",
                "shortcut unresolved menu URL branch",
            ),
            mutate_method_once(
                source,
                "FilterShortcutMenu",
                "strpos($menu, 'plugins-') === 0",
                "false",
                "shortcut plugin menu branch",
            ),
            mutate_method_once(
                source,
                "FilterShortcutMenu",
                "self::IsNavigationItemDenied($item)",
                "false",
                "shortcut denied navigation branch",
            ),
            mutate_method_once(
                source,
                "FilterShortcutMenu",
                "self::UrlContainsDeniedAdminController($url)",
                "false",
                "shortcut admin controller URL branch",
            ),
            mutate_method_once(
                source,
                "UrlContainsDeniedAdminController",
                "preg_quote($controller, '#')",
                "$controller",
                "shortcut admin controller regex escaping",
            ),
            mutate_method_once(
                source,
                "UrlContainsDeniedAdminController",
                "(?:^|[?&])s=",
                "s=",
                "shortcut query-route left boundary",
            ),
            mutate_method_once(
                source,
                "UrlContainsDeniedAdminController",
                "(?:^|/)admin/",
                "admin/",
                "shortcut path-route left boundary",
            ),
        )
        for index, mutated in enumerate(mutations):
            with self.subTest(mutation=index):
                with temporary_copy(POLICY_FILE, mutated) as path:
                    with self.assertRaises(ContractError):
                        validate_policy_file(path)

    def test_removing_navigation_fields_or_cart_button_guard_fails(self) -> None:
        source = read_utf8(POLICY_FILE)
        mutations: list[str] = []
        for field in ("control", "controller"):
            remaining = [item for item in ("control", "controller") if item != field]
            mutations.append(
                mutate_method_once(
                    source,
                    "IsNavigationItemDenied",
                    "foreach(['control', 'controller'] as $key)",
                    "foreach([" + ", ".join(f"'{item}'" for item in remaining) + "] as $key)",
                    f"navigation {field}",
                )
            )
        for field in ("url", "value", "event_value", "only_tag", "type"):
            original = ("url", "value", "event_value", "only_tag", "type")
            remaining = [item for item in original if item != field]
            mutations.append(
                mutate_method_once(
                    source,
                    "IsNavigationItemDenied",
                    "foreach(['url', 'value', 'event_value', 'only_tag', 'type'] as $key)",
                    "foreach([" + ", ".join(f"'{item}'" for item in remaining) + "] as $key)",
                    f"navigation {field}",
                )
            )
        mutations.append(
            mutate_method_once(
                source,
                "ContainsDeniedRoute",
                "self::UrlContainsDeniedWebController($value)",
                "false",
                "PATHINFO Web controller helper call",
            )
        )
        mutations.append(
            mutate_method_once(
                source,
                "UrlContainsDeniedWebController",
                "parse_url($value, PHP_URL_PATH)",
                "$value",
                "PATHINFO path parser",
            )
        )
        route_branch_mutations = (
            (
                "preg_match('#(?:^|[?&])'.preg_quote($marker, '#').'#', $value) === 1",
                "strpos($value, $marker) !== false",
                "s-query route downgraded to substring",
            ),
            (
                "preg_match('#(?:^|[=/])'.preg_quote($marker, '#').'(?=/|[.?#&]|$)#', $value) === 1",
                "strpos($value, $marker) !== false",
                "generic path route downgraded to substring",
            ),
            (
                "preg_match('#^(?:index)?'.preg_quote($marker, '#').'$#', $value) === 1",
                "strpos($value, $marker) !== false",
                "tag route downgraded to substring",
            ),
        )
        for old, new, label in route_branch_mutations:
            mutations.append(mutate_method_once(source, "ContainsDeniedRoute", old, new, label))
        mutations.append(
            mutate_method_once(
                source,
                "FilterGoodsButtons",
                "['buy', 'cart']",
                "['buy']",
                "cart button guard",
            )
        )
        for index, mutated in enumerate(mutations):
            with self.subTest(mutation=index):
                with temporary_copy(POLICY_FILE, mutated) as path:
                    with self.assertRaises(ContractError):
                        validate_policy_file(path)


class HookContractTests(unittest.TestCase):
    def test_hook_uses_abort_plugin_boundary_and_all_admin_arrays(self) -> None:
        validate_hook_file(HOOK_FILE)

    def test_critical_hook_mutations_fail_on_temporary_copy(self) -> None:
        source = read_utf8(HOOK_FILE)
        abort_mutated, abort_count = re.subn(
            r"\babort\s*\(\s*404\s*,.*?\);",
            "return null;",
            source,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertEqual(abort_count, 1)
        mutations = [
            abort_mutated,
            mutate_method_once(
                source,
                "EnforceRequestScope",
                "strtolower($controller) === 'plugins'",
                "true",
                "plugins controller boundary",
            ),
            mutate_method_once(
                source,
                "FilterAssignedViewData",
                "strtolower(RequestModule())",
                "RequestModule()",
                "case-insensitive view assignment module",
            ),
            mutate_method_once(
                source,
                "FilterAssignedViewData",
                "isset($params['data']['shortcut_menu_data'])",
                "isset($params['data']['removed_shortcut_menu_data'])",
                "shortcut_menu_data guard",
            ),
            mutate_method_once(
                source,
                "FilterAssignedViewData",
                "ScopePolicy::FilterShortcutMenu($params['data']['shortcut_menu_data'])",
                "ScopePolicy::FilterNavigation($params['data']['shortcut_menu_data'])",
                "shortcut menu filter call",
            ),
            mutate_method_once(
                source,
                "ReplaceRestrictedView",
                "DefaultTheme()",
                "'default'",
                "custom theme forced through direct default mapping",
            ),
        ]
        for key in ADMIN_PAYLOAD_KEYS:
            mutations.append(
                mutate_method_once(
                    source,
                    "FilterAdminScope",
                    f"isset($params['{key}'])",
                    f"isset($params['removed_{key}'])",
                    f"admin payload {key}",
                )
            )
        for index, mutated in enumerate(mutations):
            with self.subTest(mutation=index):
                with temporary_copy(HOOK_FILE, mutated) as path:
                    with self.assertRaises(ContractError):
                        validate_hook_file(path)


class UserViewContractTests(unittest.TestCase):
    def test_user_center_keeps_positive_features_without_px_routes(self) -> None:
        validate_view_file(USER_VIEW_FILE)

    def test_forbidden_link_and_missing_positive_link_mutations_fail(self) -> None:
        source = read_utf8(USER_VIEW_FILE)
        forbidden = source.replace(
            "{{:ModuleInclude('public/footer')}}",
            "<a href=\"{{:MyUrl('index/cart/index')}}\">cart</a>\n{{:ModuleInclude('public/footer')}}",
            1,
        )
        missing_positive = replace_once(
            source,
            "index/usergoodsfavor/index",
            "index/user/index",
            "favorite route",
        )
        fake_inquiry = source.replace(
            "{{:ModuleInclude('public/footer')}}",
            "<a href=\"/inquiry\">我的询价</a>\n{{:ModuleInclude('public/footer')}}",
            1,
        )
        for label, mutated in (
            ("forbidden cart route", forbidden),
            ("missing favorite route", missing_positive),
            ("fake inquiry placeholder", fake_inquiry),
        ):
            with self.subTest(mutation=label):
                with temporary_copy(USER_VIEW_FILE, mutated) as path:
                    with self.assertRaises(ContractError):
                        validate_view_file(path)


class GoodsModuleViewContractTests(unittest.TestCase):
    def test_goods_views_equal_pinned_upstream_with_only_cart_nodes_removed(self) -> None:
        cases = (
            (LIST_VIEW_FILE, UPSTREAM_LIST_VIEW_FILE, LIST_CART_NODE, "goods list/base"),
            (SLIDER_VIEW_FILE, UPSTREAM_SLIDER_VIEW_FILE, SLIDER_CART_NODE, "goods slider/binding"),
        )
        for plugin_path, upstream_path, cart_node, label in cases:
            with self.subTest(template=label):
                validate_goods_view_file(plugin_path, upstream_path, cart_node, label)

    def test_restored_cart_or_removed_price_link_unit_and_hooks_fail(self) -> None:
        cases = (
            (LIST_VIEW_FILE, UPSTREAM_LIST_VIEW_FILE, LIST_CART_NODE, "goods list/base"),
            (SLIDER_VIEW_FILE, UPSTREAM_SLIDER_VIEW_FILE, SLIDER_CART_NODE, "goods slider/binding"),
        )
        critical_fragments = (
            "show_price_symbol",
            "show_price_unit",
            '<strong class="price">',
            "goods_url",
        ) + EXPECTED_GOODS_VIEW_HOOKS
        for plugin_path, upstream_path, cart_node, label in cases:
            source = read_utf8(plugin_path)
            upstream_source = read_utf8(upstream_path)
            with self.subTest(template=label, mutation="restore cart"):
                with temporary_copy(plugin_path, upstream_source) as path:
                    with self.assertRaises(ContractError):
                        validate_goods_view_file(path, upstream_path, cart_node, label)
            for critical_fragment in critical_fragments:
                with self.subTest(template=label, mutation=f"remove {critical_fragment}"):
                    require(
                        critical_fragment in source,
                        f"mutation prerequisite missing from {label}: {critical_fragment}",
                    )
                    mutated = source.replace(critical_fragment, "", 1)
                    with temporary_copy(plugin_path, mutated) as path:
                        with self.assertRaises(ContractError):
                            validate_goods_view_file(path, upstream_path, cart_node, label)


class RepositoryBoundaryTests(unittest.TestCase):
    def test_plugin_tree_has_no_core_or_sql_side_effects(self) -> None:
        require(PLUGIN_ROOT.is_dir(), "nursery plugin directory is missing")
        actual_files = {
            path.relative_to(PLUGIN_ROOT).as_posix()
            for path in PLUGIN_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual_files, EXPECTED_PLUGIN_FILES)
        for relative_path in EXPECTED_PLUGIN_FILES:
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", f"app/plugins/nursery/{relative_path}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                tracked.returncode,
                0,
                f"plugin file must be tracked for clean clones: {relative_path}",
            )
        for path in PLUGIN_ROOT.rglob("*"):
            self.assertFalse(path.is_symlink(), f"plugin path must not be a symlink: {path}")
        self.assertFalse((ROOT / "app" / "event.php").exists(), "generated app/event.php must not be committed")
        self.assertEqual(list(PLUGIN_ROOT.rglob("*.sql")), [], "scope plugin must not ship SQL migrations")

        combined = "\n".join(
            read_utf8(path)
            for path in (HOOK_FILE, EVENT_FILE, POLICY_FILE)
        ).lower()
        for forbidden in (
            "config/shopxo.sql",
            "app\\service\\",
            "app\\admin\\controller\\",
            "app\\index\\controller\\",
            "app\\api\\controller\\",
            "vendor/",
            "db::",
        ):
            self.assertNotIn(forbidden, combined)

    def test_event_lifecycle_is_installable_but_data_free(self) -> None:
        validate_event_source(read_utf8(EVENT_FILE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
