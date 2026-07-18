from __future__ import annotations

import copy
import json
import re
import subprocess
import unittest
from pathlib import Path

from test_scope_contract import (
    ContractError,
    ROOT,
    compact_code,
    extract_php_method,
    read_utf8,
    replace_once,
)


PLUGIN_ROOT = ROOT / "app" / "plugins" / "nursery"
SCHEMA_FILE = PLUGIN_ROOT / "inquiry-schema-v1.json"
MIGRATION_FILE = PLUGIN_ROOT / "service" / "InquiryMigration.php"
SERVICE_FILE = PLUGIN_ROOT / "service" / "InquiryService.php"
STATE_FILE = PLUGIN_ROOT / "service" / "InquiryStateMachine.php"
BASE_SERVICE_FILE = PLUGIN_ROOT / "service" / "BaseService.php"
EVENT_FILE = PLUGIN_ROOT / "Event.php"
HOOK_FILE = PLUGIN_ROOT / "Hook.php"
CONFIG_FILE = PLUGIN_ROOT / "config.json"
WEB_CONTROLLER_FILE = PLUGIN_ROOT / "index" / "Inquiry.php"
API_CONTROLLER_FILE = PLUGIN_ROOT / "api" / "Inquiry.php"
ADMIN_CONTROLLER_FILE = PLUGIN_ROOT / "admin" / "Inquiry.php"
CLI_FILE = ROOT / "scripts" / "nursery_inquiry.php"
LOGO_FILE = ROOT / "public" / "static" / "plugins" / "nursery" / "images" / "logo.svg"
FORM_VIEW = PLUGIN_ROOT / "view" / "index" / "inquiry" / "form.html"
LIST_VIEW = PLUGIN_ROOT / "view" / "index" / "inquiry" / "index.html"
DETAIL_VIEW = PLUGIN_ROOT / "view" / "index" / "inquiry" / "detail.html"
ADMIN_LIST_VIEW = PLUGIN_ROOT / "view" / "admin" / "inquiry" / "index.html"
ADMIN_DETAIL_VIEW = PLUGIN_ROOT / "view" / "admin" / "inquiry" / "detail.html"
USER_VIEW = PLUGIN_ROOT / "view" / "index" / "user" / "index.html"
FAVORITE_VIEW = PLUGIN_ROOT / "view" / "index" / "favorite" / "index.html"
INQUIRY_JS = ROOT / "public" / "static" / "plugins" / "nursery" / "js" / "index" / "inquiry.js"
ADMIN_INQUIRY_JS = ROOT / "public" / "static" / "plugins" / "nursery" / "js" / "admin" / "inquiry-admin.js"

TABLE_KEYS = ("inquiry", "reply", "history", "duplicate_guard", "rate_limit")
TABLE_NAMES = {
    "inquiry": "sxo_plugins_nursery_inquiry",
    "reply": "sxo_plugins_nursery_inquiry_reply",
    "history": "sxo_plugins_nursery_inquiry_history",
    "duplicate_guard": "sxo_plugins_nursery_inquiry_duplicate_guard",
    "rate_limit": "sxo_plugins_nursery_inquiry_rate_limit",
}
STATUS_VALUES = ("pending", "replied", "user_viewed", "communicating", "completed", "closed")
FORBIDDEN_BUSINESS_MARKERS = (
    "notification",
    "notify",
    "analytics",
    "behavior",
    "export",
    "导出",
    "购物车",
    "订单",
    "支付",
    "供应商",
)


def method(path: Path, name: str) -> str:
    return compact_code(extract_php_method(read_utf8(path), name))


def strict_json(path: Path) -> dict:
    """Load JSON while rejecting duplicate object keys."""

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(read_utf8(path), object_pairs_hook=no_duplicates)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON root must be an object: {path}")
    return value


def validate_schema(definition: dict) -> None:
    if definition.get("schema_version") != 1 or definition.get("inquiry_schema_version") != 1:
        raise ContractError("schema v1 version markers are required")
    tables = definition.get("tables")
    if not isinstance(tables, dict) or tuple(tables) != TABLE_KEYS:
        raise ContractError("schema must contain the five tables in fixed order")
    for key in TABLE_KEYS:
        table = tables[key]
        if not isinstance(table, dict):
            raise ContractError(f"invalid table definition: {key}")
        if table.get("name") != TABLE_NAMES[key]:
            raise ContractError(f"unexpected physical table name: {key}")
        if table.get("engine") != "InnoDB" or table.get("charset") != "utf8mb4":
            raise ContractError(f"table encoding/engine drift: {key}")
        if table.get("collation") != "utf8mb4_unicode_ci":
            raise ContractError(f"table collation drift: {key}")
        columns = table.get("columns")
        indexes = table.get("indexes")
        if not isinstance(columns, list) or not isinstance(indexes, list):
            raise ContractError(f"columns/indexes must be arrays: {key}")
        names = [column.get("name") for column in columns if isinstance(column, dict)]
        if len(names) != len(set(names)) or len(names) != len(columns):
            raise ContractError(f"duplicate/invalid columns: {key}")
        index_names = [index.get("name") for index in indexes if isinstance(index, dict)]
        if len(index_names) != len(set(index_names)) or len(index_names) != len(indexes):
            raise ContractError(f"duplicate/invalid indexes: {key}")
        if "PRIMARY" not in index_names:
            raise ContractError(f"missing primary key: {key}")
        if any("foreign" in json.dumps(table, ensure_ascii=False).lower() for _ in [0]):
            raise ContractError(f"foreign key metadata is not allowed: {key}")

    inquiry_columns = {column["name"]: column for column in tables["inquiry"]["columns"]}
    required_columns = {
        "id",
        "inquiry_no",
        "user_id",
        "goods_id",
        "goods_title",
        "goods_images",
        "goods_status",
        "reference_price",
        "reference_min",
        "reference_max",
        "reference_unit",
        "spec_base_id",
        "spec_snapshot",
        "quantity",
        "quantity_unit",
        "contact_name",
        "contact_phone",
        "contact_phone_hash",
        "region_province_id",
        "region_city_id",
        "region_county_id",
        "region_province_name",
        "region_city_name",
        "region_county_name",
        "region_province_code",
        "region_city_code",
        "region_county_code",
        "address",
        "expected_date",
        "need_transport",
        "need_loading",
        "need_planting",
        "user_note",
        "status",
        "first_replied_at",
        "created_at",
        "updated_at",
    }
    if set(inquiry_columns) != required_columns:
        raise ContractError("inquiry snapshot columns are incomplete or widened")
    if inquiry_columns["contact_phone"]["type"] != "varbinary(255)":
        raise ContractError("phone must be encrypted at rest")
    if inquiry_columns["contact_phone_hash"]["type"] != "char(64)":
        raise ContractError("phone hash must be fixed-width HMAC")
    if inquiry_columns["spec_snapshot"]["type"] != "json":
        raise ContractError("spec snapshot must be structured JSON")
    if inquiry_columns["user_id"]["nullable"] or inquiry_columns["goods_id"]["nullable"]:
        raise ContractError("ownership/product IDs may not be nullable")

    guard = {index["name"]: index for index in tables["duplicate_guard"]["indexes"]}
    unique = guard.get("uniq_nursery_inquiry_duplicate_guard")
    if not unique or unique.get("unique") is not True:
        raise ContractError("duplicate guard must be unique")
    if unique.get("columns") != ["user_id", "goods_id", "fingerprint_version", "fingerprint_digest"]:
        raise ContractError("duplicate guard key order changed")
    rate = {index["name"]: index for index in tables["rate_limit"]["indexes"]}
    if rate.get("PRIMARY", {}).get("columns") != ["user_id"]:
        raise ContractError("rate limit must be one row per user")
    ledger = definition.get("ledger")
    if not isinstance(ledger, dict) or ledger.get("only_tag") != "plugins_nursery_inquiry_schema_v1":
        raise ContractError("schema ledger only_tag changed")


def assert_tokens(source: str, tokens: tuple[str, ...], label: str) -> None:
    compact = compact_code(source)
    missing = [token for token in tokens if token.lower() not in compact]
    if missing:
        raise ContractError(f"{label} missing tokens: {missing}")


class InquirySchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definition = strict_json(SCHEMA_FILE)
        validate_schema(cls.definition)

    def test_schema_has_fixed_five_tables_and_snapshot_fields(self) -> None:
        self.assertEqual(tuple(self.definition["tables"]), TABLE_KEYS)
        self.assertEqual(
            [self.definition["tables"][key]["name"] for key in TABLE_KEYS],
            list(TABLE_NAMES.values()),
        )
        self.assertEqual(self.definition["tables"]["inquiry"]["engine"], "InnoDB")
        self.assertEqual(self.definition["tables"]["inquiry"]["collation"], "utf8mb4_unicode_ci")

    def test_schema_mutations_fail_closed(self) -> None:
        missing = copy.deepcopy(self.definition)
        missing["tables"]["inquiry"]["columns"] = [
            column
            for column in missing["tables"]["inquiry"]["columns"]
            if column["name"] != "goods_status"
        ]
        with self.assertRaises(ContractError):
            validate_schema(missing)

        altered = copy.deepcopy(self.definition)
        altered["tables"]["duplicate_guard"]["indexes"][1]["columns"] = [
            "user_id",
            "goods_id",
            "fingerprint_digest",
            "fingerprint_version",
        ]
        with self.assertRaises(ContractError):
            validate_schema(altered)

    def test_no_sql_secret_or_personal_data_is_embedded(self) -> None:
        source = read_utf8(SCHEMA_FILE).lower()
        for forbidden in ("create table", "insert into", "drop table", "hmac_key", "13800138000", "password"):
            self.assertNotIn(forbidden, source)


class InquiryMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read_utf8(MIGRATION_FILE)
        cls.compact = compact_code(cls.source)

    def test_preflight_and_status_are_read_only(self) -> None:
        for name in ("Status", "Preflight"):
            body = method(MIGRATION_FILE, name)
            self.assertIn("self::definition()", body)
            self.assertIn("self::inspect($definition", body)
            self.assertIn("self::readledger($definition", body)
            self.assertIn("'write_performed'=>false", body)
            for forbidden in ("starttrans(", "create table", "alter table", "writeledger(", "->insert(", "->update("):
                self.assertNotIn(forbidden, body)

    def test_run_uses_lock_information_schema_forward_repair_and_ledger_last(self) -> None:
        run = method(MIGRATION_FILE, "Run")
        assert_tokens(
            run,
            (
                "self::validateexecutionmetadata($actor,$run_id)",
                "self::acquireexecutionlock()",
                "self::inspect($definition,$connection)",
                "self::findrun(",
                "self::createtable($definition,$key,$connection)",
                "self::createmissingindexes(",
                "self::writeledger(",
                "self::assertready($connection)",
                "'replayed'=>true",
            ),
            "InquiryMigration::Run",
        )
        self.assertIn("get_lock(", self.compact)
        self.assertIn("release_lock(", self.compact)
        self.assertIn("information_schema.tables", self.compact)
        self.assertIn("information_schema.columns", self.compact)
        self.assertIn("information_schema.statistics", self.compact)
        self.assertIn("referenced_table_name", self.compact)
        self.assertLess(run.index("self::inspect($definition,$connection)"), run.index("self::writeledger("))
        self.assertNotRegex(self.compact, r"drop\s+table|truncate\s+table|delete\s+from")

    def test_runtime_gate_checks_actual_structure_and_matching_ledger(self) -> None:
        ready = method(MIGRATION_FILE, "AssertReady")
        assert_tokens(
            ready,
            ("self::inspect($definition,$connection)", "!$inspection['ready']", "self::readledger($definition,$connection,false)===null"),
            "InquiryMigration::AssertReady",
        )

    def test_migration_source_mutations_are_detected(self) -> None:
        run = method(MIGRATION_FILE, "Run")
        mutated = replace_once(run, "self::createmissingindexes(", "/* removed */", "missing index repair")
        with self.assertRaises(ContractError):
            assert_tokens(mutated, ("self::createmissingindexes(",), "mutation")
        mutated = replace_once(run, "self::writeledger(", "/* removed */", "ledger write")
        with self.assertRaises(ContractError):
            assert_tokens(mutated, ("self::writeledger(",), "mutation")

    def test_cli_is_explicit_and_does_not_execute_shell_or_install_sql(self) -> None:
        source = compact_code(read_utf8(CLI_FILE))
        self.assertIn("['status','preflight','migrate']", source)
        self.assertIn("migraterequires--actorand--run-id", source)
        self.assertIn("inquirymigration::status()", source)
        self.assertIn("inquirymigration::preflight()", source)
        self.assertIn("inquirymigration::run($options['actor'],$options['run-id'])", source)
        for forbidden in ("shell_exec(", "system(", "passthru(", "config/shopxo.sql", "install.sql", "drop table"):
            self.assertNotIn(forbidden, source)

    def test_event_install_and_upgrade_only_preflight_all_migrations(self) -> None:
        event = compact_code(read_utf8(EVENT_FILE))
        preflight = method(EVENT_FILE, "PreflightAll")
        self.assertIn("$this->preflightall($params)", event)
        self.assertIn("catalogmigration::preflight(", preflight)
        self.assertIn("favoritemigration::preflight()", preflight)
        self.assertIn("inquirymigration::preflight()", preflight)
        self.assertNotIn("inquirymigration::run(", event)
        self.assertNotIn("db::", preflight)


class InquiryStateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read_utf8(STATE_FILE)
        cls.compact = compact_code(cls.source)

    def test_state_values_and_transition_matrix_are_explicit(self) -> None:
        for value in STATUS_VALUES:
            self.assertIn(f"const{value}='{value}'", self.compact)
        self.assertIn("self::pending=>[self::closed]", self.compact)
        self.assertIn("self::replied=>[self::communicating,self::completed,self::closed]", self.compact)
        self.assertIn("self::user_viewed=>[self::communicating,self::completed,self::closed]", self.compact)
        self.assertIn("self::communicating=>[self::completed,self::closed]", self.compact)
        self.assertIn("self::completed=>[]", self.compact)
        self.assertIn("self::closed=>[]", self.compact)

    def test_reply_user_view_and_reopen_rules_are_separate(self) -> None:
        reply = method(STATE_FILE, "ReplyTarget")
        user_view = method(STATE_FILE, "UserViewTarget")
        reopen = method(STATE_FILE, "AssertReopen")
        self.assertIn("self::reply_from", reply)
        self.assertIn("returnself::replied", reply)
        self.assertIn("$current===self::replied", user_view)
        self.assertIn("self::isterminal($from)", reopen)
        self.assertIn("trim($reason)===''", reopen)
        self.assertIn("returnself::communicating", reopen)
        self.assertNotIn("self::completed,self::closed", compact_code(reply))

    def test_state_mutation_is_detectable(self) -> None:
        mutated = self.compact.replace("self::communicating=>[self::completed,self::closed]", "self::communicating=>[]", 1)
        self.assertNotIn("self::communicating=>[self::completed,self::closed]", mutated)


class InquiryServiceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read_utf8(SERVICE_FILE)
        cls.compact = compact_code(cls.source)

    def test_user_methods_use_injected_identity_and_runtime_schema_gate(self) -> None:
        for name in ("FormData", "Submit", "UserList", "UserDetail"):
            body = method(SERVICE_FILE, name)
            self.assertIn("self::authenticateduserid($user)", body, name)
            self.assertIn("self::assertready()", body, name)
        self.assertIn("$where=['user_id'=>$user_id]", method(SERVICE_FILE, "UserList"))
        detail = method(SERVICE_FILE, "UserDetail")
        self.assertIn("'user_id'=>$user_id", detail)
        self.assertIn("status'=>inquirystatemachine::replied", detail)
        for name in ("FormData", "Submit", "UserList", "UserDetail"):
            body = method(SERVICE_FILE, name)
            self.assertNotIn("$params['user_id']", body)
            self.assertNotIn("$params['user']=", body)

    def test_submission_reloads_published_price_and_structured_spec_from_server(self) -> None:
        validate = method(SERVICE_FILE, "ValidateSubmission")
        snapshot = method(SERVICE_FILE, "PublishedGoodsSnapshot")
        spec = method(SERVICE_FILE, "BuildSpecOption")
        for token in (
            "self::strictunsignedid($params['goods_id']",
            "self::normalizequantity(",
            "self::normalizephone(",
            "self::validatedregion(",
            "self::normalizetext($params['user_note']",
            "self::instancesecret()",
            "hash_hmac('sha256'",
            "json_preserve_zero_fraction",
            "ksort($canonical,sort_string)",
            "'ordered_specification'",
            "'price'=>$snapshot['selected_spec']['price']",
            "'unit'=>$snapshot['selected_spec']['unit']",
        ):
            self.assertIn(token, validate)
        spec_types = method(SERVICE_FILE, "GoodsSpecTypes")
        for token in (
            "is_shelves",
            "is_delete_time",
            "referencepriceservice::assertpublishedgoods(",
            "goodsspecbase",
            "self::buildspecoption(",
        ):
            self.assertIn(token, snapshot)
        self.assertIn("db::name('goodsspectype')", spec_types)
        self.assertIn("db::name('goodsspecvalue')", method(SERVICE_FILE, "BuildSpecOption"))
        for token in ("$base_id", "goods_id", "self::validstoredprice(", "items", "unit"):
            self.assertIn(token, spec)
        self.assertNotIn("$params['price']", validate)
        self.assertNotIn("$params['title']", validate)
        self.assertNotIn("$params['images']", validate)

    def test_snapshot_creation_is_atomic_and_does_not_touch_favorites_or_prices(self) -> None:
        create = method(SERVICE_FILE, "CreateInquiry")
        submit = method(SERVICE_FILE, "Submit")
        for token in (
            "starttrans()",
            "lock(true)",
                "self::table($connection,'pluginsnurseryinquiryduplicateguard')",
                "insertgetid($inquiry_data)",
                "self::appendhistory(",
                "'event_type'=>'created'",
            "$connection->commit()",
        ):
            self.assertIn(token, create)
        self.assertIn("self::consumeratelimit($user_id)", submit)
        for forbidden in (
            "goodsfavor",
            "favoritemigration",
            "favoriteservice",
            "goodsservice::save",
            "goods_spec_base')->update",
            "sxo_goods",
            "myeventtrigger",
            "eventservice",
        ):
            self.assertNotIn(forbidden, self.compact)
        self.assertNotIn("->delete(", create)
        self.assertNotIn("->truncate(", create)

    def test_rate_limit_is_independent_first_transaction_and_fixed_window(self) -> None:
        submit = method(SERVICE_FILE, "Submit")
        consume = method(SERVICE_FILE, "ConsumeRateLimit")
        self.assertLess(submit.index("self::consumeratelimit($user_id)"), submit.index("self::createinquiry("))
        for token in (
            "starttrans()",
            "lock(true)",
            "window_started_at",
            "attempt_count",
            "rate_window_seconds",
            "rate_max_attempts",
            "elapsed>=self::rate_window_seconds",
            "count>=self::rate_max_attempts",
            "$connection->commit()",
            "isduplicatekeyerror",
        ):
            self.assertIn(token, consume)
        self.assertNotIn("ip_address", consume)
        self.assertNotIn("contact_phone", consume)
        self.assertNotIn("fingerprint", consume)

    def test_status_reply_history_and_reveal_are_append_only_and_authorized(self) -> None:
        for name, action in (
            ("AdminList", "index"),
            ("AdminDetail", "detail"),
            ("AdminReply", "reply"),
            ("AdminContactReveal", "contactreveal"),
        ):
            body = method(SERVICE_FILE, name)
            self.assertIn(f"self::authenticatedadmin($admin,'{action}')", body, name)
        reply = method(SERVICE_FILE, "AdminReply")
        self.assertIn("inquirystatemachine::replytarget", reply)
        self.assertIn("insertgetid(array_merge($reply", reply)
        self.assertIn("self::appendhistory(", reply)
        self.assertIn("$connection->commit()", reply)
        transition = method(SERVICE_FILE, "AdminTransition")
        self.assertIn("self::admintransition($admin,$params,false)", method(SERVICE_FILE, "AdminStatusUpdate"))
        self.assertIn("self::admintransition($admin,$params,true)", method(SERVICE_FILE, "AdminReopen"))
        self.assertIn("self::authenticatedadmin($admin,$action)", transition)
        self.assertIn("self::assertauditreasonsafe($reason,(string)$inquiry['contact_phone'])", transition)
        self.assertIn("privatestaticfunctionassertauditreasonsafe", self.compact)
        self.assertNotIn("assertauditreasonsafe($reason", reply)
        self.assertIn("inquirystatemachine::assertadmintransition", transition)
        self.assertIn("inquirystatemachine::assertreopen", transition)
        reveal = method(SERVICE_FILE, "AdminContactReveal")
        self.assertIn("'event_type'=>'contact_reveal'", reveal)
        self.assertLess(reveal.index("self::appendhistory("), reveal.index("self::decryptphone("))
        self.assertNotIn("contact_phone' =>", reveal)
        self.assertNotIn("->delete(", self.compact)

    def test_phone_secret_and_normalization_fail_closed(self) -> None:
        secret_method = method(SERVICE_FILE, "InstanceSecret")
        phone = method(SERVICE_FILE, "NormalizePhone")
        encrypt = method(SERVICE_FILE, "EncryptPhone")
        decrypt = method(SERVICE_FILE, "DecryptPhone")
        self.assertIn("myenv(self::hmac_env_key,null)", secret_method)
        self.assertIn("strlen($instance_key)<32", secret_method)
        self.assertIn("change-me", secret_method)
        self.assertIn("preg_match", phone)
        self.assertIn("hash_hmac('sha256'", self.compact)
        self.assertIn("aes-256-gcm", encrypt)
        self.assertIn("hash_hkdf", encrypt)
        self.assertIn("openssl_decrypt", decrypt)
        self.assertNotIn("nursery_inquiry_hmac_key =", self.compact)

    def test_admin_filters_cover_required_dimensions_and_mask_default(self) -> None:
        filters = method(SERVICE_FILE, "ApplyAdminFilters")
        for token in (
            "inquiry_no",
            "goods_title",
            "user_id",
            "user_keyword",
            "contact_phone_hash",
            "status",
            "region_province_id",
            "region_city_id",
            "region_county_id",
            "created_start",
            "created_end",
            "is_overdue",
            "date_sub(now(),interval24hour)",
        ):
            self.assertIn(token, filters)
        admin_list = method(SERVICE_FILE, "AdminList")
        admin_detail = method(SERVICE_FILE, "AdminDetail")
        self.assertIn("self::decorateinquiryrow($item,true)", admin_list)
        self.assertIn("self::detailresponse($inquiry,false)", admin_detail)
        detail_response = method(SERVICE_FILE, "DetailResponse")
        self.assertIn("self::decorateinquiryrow($inquiry,true)", detail_response)
        self.assertIn("$row['contact_phone_masked']", method(SERVICE_FILE, "DecorateInquiryRow"))


class InquiryPermissionAndEntryContractTests(unittest.TestCase):
    def test_base_service_declares_six_independent_actions(self) -> None:
        source = compact_code(read_utf8(BASE_SERVICE_FILE))
        for action in ("index", "detail", "reply", "statusupdate", "contactreveal", "reopen"):
            self.assertIn(f"'action'=>'{action}'", source)
        self.assertIn("'control'=>'inquiry'", source)

    def test_controllers_use_only_gateway_context_and_web_nonce(self) -> None:
        web = compact_code(read_utf8(WEB_CONTROLLER_FILE))
        api = compact_code(read_utf8(API_CONTROLLER_FILE))
        admin = compact_code(read_utf8(ADMIN_CONTROLLER_FILE))
        self.assertIn("$this->user=isset($params['user'])&&is_array($params['user'])?$params['user']:[]", web)
        self.assertIn("$this->user=isset($params['user'])&&is_array($params['user'])?$params['user']:[]", api)
        self.assertIn("$this->admin=isset($params['admin'])&&is_array($params['admin'])?$params['admin']:[]", admin)
        self.assertIn("request()->ispost()", api)
        self.assertIn("inquiryservice::validatewebwrite($params,'user')", web)
        self.assertIn("inquiryservice::validatewebwrite($params,'admin')", admin)
        for source in (web, api, admin):
            self.assertNotIn("$params['user_id']", source)
            self.assertNotIn("$params['admin_id']", source)

    def test_config_registers_real_inquiry_hooks_and_local_logo(self) -> None:
        config = strict_json(CONFIG_FILE)
        hooks = config["hook"]
        for hook in (
            "plugins_service_goods_buy_nav_button_handle",
            "plugins_service_users_center_left_menu_handle",
            "plugins_service_admin_menu_data",
            "plugins_view_assign_data",
        ):
            self.assertEqual(hooks.get(hook), [r"app\plugins\nursery\Hook"])
        logo = config["base"]["logo"]
        self.assertTrue(logo.startswith("/static/plugins/nursery/"))
        self.assertTrue(LOGO_FILE.is_file())
        svg = read_utf8(LOGO_FILE).lower()
        self.assertIn("<svg", svg)
        for forbidden in ("<script", "javascript:", "href=\"http", "xlink:href=\"http", "<text", "<foreignobject"):
            self.assertNotIn(forbidden, svg)

    def test_hook_adds_inquiry_after_commerce_filter_and_checks_admin_scope(self) -> None:
        source = read_utf8(HOOK_FILE)
        handle = method(HOOK_FILE, "handle")
        self.assertIn("scopepolicy::filtergoodsbuttons", handle)
        self.assertIn("$this->appendinquirybutton($params)", handle)
        self.assertIn("$this->injectuserinquiry menu".replace(" ", ""), handle)
        self.assertIn("$this->filteradminscope($params)", handle)
        self.assertIn("admin_plugins", source)
        self.assertIn("inquiry-index", compact_code(source))
        append = method(HOOK_FILE, "AppendInquiryButton")
        self.assertIn("pluginshomeurl('nursery','inquiry','form'", append)
        self.assertIn("is_shelves", append)
        self.assertNotIn("index/cart", compact_code(source))


class InquiryUiAndBoundaryContractTests(unittest.TestCase):
    def test_form_contains_required_fields_and_real_post_endpoint(self) -> None:
        source = read_utf8(FORM_VIEW)
        for field in (
            "goods_id",
            "spec_base_id",
            "quantity",
            "contact_name",
            "contact_phone",
            "region_province_id",
            "region_city_id",
            "region_county_id",
            "address",
            "expected_date",
            "need_transport",
            "need_loading",
            "need_planting",
            "user_note",
            "request_nonce",
        ):
            self.assertIn(f'name="{field}"', source)
        self.assertIn("PluginsHomeUrl('nursery', 'inquiry', 'create')", source)
        self.assertIn("StaticAttachmentUrl('inquiry.js'", source)
        self.assertNotIn("index/cart", source.lower())

    def test_user_and_admin_views_expose_history_without_sensitive_placeholders(self) -> None:
        user_list = read_utf8(LIST_VIEW)
        user_detail = read_utf8(DETAIL_VIEW)
        admin_list = read_utf8(ADMIN_LIST_VIEW)
        admin_detail = read_utf8(ADMIN_DETAIL_VIEW)
        user_center = read_utf8(USER_VIEW)
        for source in (user_list, user_detail, admin_list, admin_detail):
            self.assertIn("inquiry", source.lower())
            for marker in ("购物车", "订单", "支付", "导出", "通知"):
                self.assertNotIn(marker, source)
        for token in ("回复", "报价有效期", "状态时间线", "goods_images", "reference_price"):
            self.assertIn(token, user_detail)
        for token in ("latest_reply_at_text", "latest_reply_valid_until", "回复时间", "报价有效期"):
            self.assertIn(token, user_list)
        for token in ("contact_phone_masked", "contactreveal", "stock_note", "available_spec", "statusupdate", "reopen"):
            self.assertIn(token, admin_detail)
        self.assertIn("PluginsHomeUrl('nursery', 'inquiry', 'index')", read_utf8(HOOK_FILE))
        self.assertIn("inquiry_url", read_utf8(FAVORITE_VIEW))

    def test_write_javascript_is_post_only_nonce_bound_and_double_click_safe(self) -> None:
        user_js = compact_code(read_utf8(INQUIRY_JS))
        admin_js = compact_code(read_utf8(ADMIN_INQUIRY_JS))
        self.assertIn("type:'post'", user_js)
        self.assertIn("data:form.serialize()", user_js)
        self.assertIn("data:{id:button.attr('data-id')||'',request_nonce:button.attr('data-nonce')||''}", admin_js)
        self.assertIn("type:'post'", admin_js)
        self.assertIn("data('pending')===true", user_js)
        self.assertIn("data('pending')===true", admin_js)

    def test_no_core_or_shopxo_schema_files_changed_for_inquiry(self) -> None:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main", "--", "app", "config/shopxo.sql", "vendor"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        paths = [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
        registered_core_paths = set()
        register_path = ROOT / ".harness" / "core-changes" / "REGISTER.md"
        if register_path.is_file():
            for line in register_path.read_text(encoding="utf-8").splitlines():
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                if (
                    len(cells) >= 8
                    and cells[0] == "NUR-SEC-001"
                    and cells[2] == "app/service/GoodsService.php"
                    and cells[6] == "Codex-Review"
                    and cells[7] == "approved"
                ):
                    registered_core_paths.add(cells[2])
        forbidden = [
            path
            for path in paths
            if path == "config/shopxo.sql"
            or (path.startswith("app/service/") and path not in registered_core_paths)
            or path.startswith("app/index/view/default/")
            or path.startswith("vendor/")
        ]
        self.assertEqual(forbidden, [])

    def test_service_and_views_do_not_introduce_unapproved_side_channels(self) -> None:
        sources = "\n".join(
            read_utf8(path).lower()
            for path in (SERVICE_FILE, WEB_CONTROLLER_FILE, API_CONTROLLER_FILE, ADMIN_CONTROLLER_FILE, FORM_VIEW, LIST_VIEW, DETAIL_VIEW, ADMIN_LIST_VIEW, ADMIN_DETAIL_VIEW)
        )
        for marker in FORBIDDEN_BUSINESS_MARKERS:
            self.assertNotIn(marker, sources)
        for marker in ("goodsfavor", "favoriteservice", "myeventtrigger", "eventservice"):
            self.assertNotIn(marker, compact_code(read_utf8(SERVICE_FILE)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
