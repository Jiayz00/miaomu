from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from test_scope_contract import ROOT, compact_code, extract_php_method, read_utf8


PLUGIN_ROOT = ROOT / "app" / "plugins" / "nursery"
MANIFEST_FILE = PLUGIN_ROOT / "favorite-schema-v1.json"
MIGRATION_FILE = PLUGIN_ROOT / "service" / "FavoriteMigration.php"
SERVICE_FILE = PLUGIN_ROOT / "service" / "FavoriteService.php"
WEB_CONTROLLER_FILE = PLUGIN_ROOT / "index" / "Favorite.php"
API_CONTROLLER_FILE = PLUGIN_ROOT / "api" / "Favorite.php"
HOOK_FILE = PLUGIN_ROOT / "Hook.php"
POLICY_FILE = PLUGIN_ROOT / "service" / "ScopePolicy.php"
EVENT_FILE = PLUGIN_ROOT / "Event.php"
CONFIG_FILE = PLUGIN_ROOT / "config.json"
CLI_FILE = ROOT / "scripts" / "nursery_favorite.php"
JS_FILE = ROOT / "public" / "static" / "plugins" / "nursery" / "js" / "index" / "favorite.js"
CSS_FILE = ROOT / "public" / "static" / "plugins" / "nursery" / "css" / "index" / "favorite.css"
FAVORITE_VIEW_FILE = PLUGIN_ROOT / "view" / "index" / "favorite" / "index.html"
DETAIL_VIEW_FILE = (
    PLUGIN_ROOT
    / "view"
    / "index"
    / "goods"
    / "module"
    / "middle_base"
    / "left"
    / "photo_pc_bottom_favor.html"
)
CARD_VIEW_FILES = (
    PLUGIN_ROOT / "view" / "index" / "module" / "goods" / "grid" / "base.html",
    PLUGIN_ROOT / "view" / "index" / "module" / "goods" / "list" / "base.html",
    PLUGIN_ROOT / "view" / "index" / "module" / "goods" / "slider" / "binding.html",
)


def method(path: Path, name: str) -> str:
    return compact_code(extract_php_method(read_utf8(path), name))


class FavoriteMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        cls.source = read_utf8(MIGRATION_FILE)
        cls.compact = compact_code(cls.source)

    def test_manifest_pins_version_table_index_and_ledger(self) -> None:
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["favorite_schema_version"], 1)
        self.assertEqual(self.manifest["table"], "goods_favor")
        self.assertEqual(
            self.manifest["unique_index"],
            {"name": "uniq_nursery_user_goods", "columns": ["user_id", "goods_id"]},
        )
        self.assertEqual(
            self.manifest["ledger"]["only_tag"],
            "plugins_nursery_favorite_schema_v1",
        )

    def test_preflight_is_read_only_and_reports_migration_requirement(self) -> None:
        preflight = method(MIGRATION_FILE, "Preflight")
        for forbidden in ("createuniqueindex(", "writeledger(", "->insert", "->update(", "db::execute("):
            self.assertNotIn(forbidden, preflight)
        self.assertIn("self::inspect($definition,true)", preflight)
        self.assertIn("'migration_required'=>!$inspection['ready']", preflight)
        self.assertIn("'write_performed'=>false", preflight)

    def test_duplicates_fail_before_any_unique_ddl(self) -> None:
        inspect = method(MIGRATION_FILE, "Inspect")
        self.assertIn("self::duplicatesummary($table)", inspect)
        self.assertIn("$duplicates['duplicate_groups']>0", inspect)
        self.assertIn("thrownew\\runtimeexception(", inspect)
        run = method(MIGRATION_FILE, "Run")
        self.assertLess(run.index("self::inspect($definition,true)"), run.index("self::createuniqueindex($definition)"))
        self.assertNotIn("->delete(", self.compact)
        self.assertNotIn("goodsfavor')->update(", self.compact)

    def test_unique_index_is_ordered_user_then_goods_and_verified_from_schema(self) -> None:
        create = method(MIGRATION_FILE, "CreateUniqueIndex")
        indexes = method(MIGRATION_FILE, "Indexes")
        self.assertIn("adduniqueindex`'.$name.'`", create)
        self.assertIn("(`user_id`,`goods_id`)", create)
        self.assertIn("showindexfrom", indexes)
        self.assertIn("seq_in_index", indexes)
        self.assertIn("column_name", indexes)
        self.assertIn("non_unique", indexes)

    def test_runtime_write_gate_requires_actual_index_and_matching_ledger(self) -> None:
        ready = method(MIGRATION_FILE, "AssertReady")
        self.assertIn("self::inspect($definition,false)", ready)
        self.assertIn("!$inspection['ready']", ready)
        self.assertIn("self::readledger($definition,false)===null", ready)
        add = method(SERVICE_FILE, "Add")
        self.assertLess(add.index("favoritemigration::assertready()"), add.index("->insert("))

    def test_migration_is_locked_idempotent_and_forward_repairs_ledger(self) -> None:
        run = method(MIGRATION_FILE, "Run")
        for token in (
            "self::validateexecutionmetadata($actor,$run_id)",
            "self::acquireexecutionlock()",
            "self::findrun(",
            "self::createuniqueindex($definition)",
            "self::writeledger(",
            "self::assertready()",
            "'replayed'=>true",
        ):
            self.assertIn(token, run)
        self.assertIn("get_lock(", self.source.lower())
        self.assertIn("release_lock(", self.source.lower())

    def test_cli_accepts_only_status_preflight_and_explicit_migrate(self) -> None:
        source = compact_code(read_utf8(CLI_FILE))
        self.assertIn("['status','preflight','migrate']", source)
        self.assertIn("migraterequires--actorand--run-id", source)
        self.assertIn("favoritemigration::status()", source)
        self.assertIn("favoritemigration::preflight()", source)
        self.assertIn("favoritemigration::run($options['actor'],$options['run-id'])", source)
        for forbidden in ("install.sql", "config/shopxo.sql", "shell_exec(", "system(", "passthru("):
            self.assertNotIn(forbidden, source)

    def test_install_and_upgrade_only_run_combined_preflight(self) -> None:
        event = compact_code(read_utf8(EVENT_FILE))
        preflight = method(EVENT_FILE, "PreflightAll")
        self.assertIn("favoritemigration::preflight()", preflight)
        self.assertIn("catalogmigration::preflight(", preflight)
        self.assertNotIn("favoritemigration::run(", event)


class FavoriteServiceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read_utf8(SERVICE_FILE)
        cls.compact = compact_code(cls.source)

    def test_add_is_explicit_idempotent_insert_not_toggle(self) -> None:
        add = method(SERVICE_FILE, "Add")
        self.assertIn("favoritemigration::assertready()", add)
        self.assertIn("self::assertgoodscanbefavorited($goods_id)", add)
        self.assertIn("db::name('goodsfavor')->insert(", add)
        self.assertIn("self::isduplicatekeyerror($write_error)", add)
        self.assertIn("self::ownpairexists($user_id,$goods_id)", add)
        for forbidden in ("->delete(", "toggle", "goodsfavorcancel", "is_mandatory_favor"):
            self.assertNotIn(forbidden, add)

    def test_only_duplicate_key_can_be_treated_as_successful_replay(self) -> None:
        duplicate = method(SERVICE_FILE, "IsDuplicateKeyError")
        self.assertIn("'1062'", duplicate)
        self.assertIn("'23000'", duplicate)
        self.assertIn("duplicateentry", duplicate)
        add = method(SERVICE_FILE, "Add")
        self.assertIn("!self::isduplicatekeyerror($write_error)||!self::ownpairexists(", add)

    def test_cancel_is_idempotent_and_always_scoped_to_authenticated_pair(self) -> None:
        cancel = method(SERVICE_FILE, "Cancel")
        self.assertIn("['user_id'=>$user_id,'goods_id'=>$goods_id]", cancel)
        self.assertIn("->delete()", cancel)
        self.assertIn("self::stateresponse($goods_id,false", cancel)
        self.assertNotIn("favorite_id", cancel)
        self.assertNotIn("$params['user_id']", cancel)
        self.assertNotIn("$params['user']", cancel)

    def test_status_and_list_are_user_scoped_without_existence_or_row_id_leaks(self) -> None:
        status = method(SERVICE_FILE, "Status")
        listing = method(SERVICE_FILE, "Listing")
        self.assertIn("self::ownpairexists($user_id,$goods_id)", status)
        self.assertIn("where(['user_id'=>$user_id])", listing)
        self.assertIn("where(['f.user_id'=>$user_id])", listing)
        self.assertNotIn("f.id", listing.split("->field(", 1)[1].split(")->", 1)[0])
        for token in ("$params['user_id']", "$params['user']", "favorite_id", "system_user"):
            self.assertNotIn(token, status)
            self.assertNotIn(token, listing)

    def test_list_left_join_preserves_off_shelf_deleted_and_missing_goods(self) -> None:
        listing = method(SERVICE_FILE, "Listing")
        self.assertIn("->leftjoin('goodsg','g.id=f.goods_id')", listing)
        self.assertIn("$state='active'", listing)
        self.assertIn("$state='off_shelf'", listing)
        self.assertIn("$state='deleted'", listing)
        self.assertIn("$row['can_view']=($state==='active')", listing)
        self.assertIn("$row['goods_url']=$row['can_view']?", listing)
        where_tail = listing[listing.index("->leftjoin(") : listing.index("->field(")]
        self.assertNotIn("g.is_delete_time", where_tail)
        self.assertNotIn("g.is_shelves", where_tail)

    def test_add_rejects_missing_deleted_and_off_shelf_goods(self) -> None:
        guard = method(SERVICE_FILE, "AssertGoodsCanBeFavorited")
        self.assertIn("where(['id'=>$goods_id])", guard)
        self.assertIn("intval($goods['is_delete_time'])!==0", guard)
        self.assertIn("intval($goods['is_shelves'])!==1", guard)
        self.assertIn("thrownew\\runtimeexception(", guard)

    def test_goods_id_is_one_strict_positive_integer(self) -> None:
        strict = method(SERVICE_FILE, "StrictGoodsId")
        self.assertIn("/^[1-9][0-9]*$/d", strict)
        self.assertNotIn("explode(", strict)
        self.assertNotIn("is_array(", strict)
        self.assertNotIn("favorite_id", strict)

    def test_web_writes_are_ajax_post_with_session_bound_csrf(self) -> None:
        validate = method(SERVICE_FILE, "ValidateWebWrite")
        token = method(SERVICE_FILE, "WebCsrfToken")
        self.assertIn("!request()->ispost()||!is_ajax", validate)
        self.assertIn("mysession(self::csrf_session_key)", validate)
        self.assertIn("hash_equals($expected,$provided)", validate)
        self.assertIn("random_bytes(32)", token)
        self.assertIn("mysession(self::csrf_session_key,$token)", token)

    def test_api_writes_are_post_and_use_gateway_user_context(self) -> None:
        source = compact_code(read_utf8(API_CONTROLLER_FILE))
        constructor = method(API_CONTROLLER_FILE, "__construct")
        for action in ("Add", "Cancel"):
            self.assertIn("request()->ispost()", method(API_CONTROLLER_FILE, action))
        self.assertIn("$this->user", constructor)
        self.assertIn("favoriteservice::add($this->user,$params)", source)
        self.assertIn("favoriteservice::cancel($this->user,$params)", source)
        self.assertNotIn("$params['user_id']", source)

    def test_web_controller_never_promotes_request_user_fields(self) -> None:
        source = compact_code(read_utf8(WEB_CONTROLLER_FILE))
        self.assertIn("favoriteservice::validatewebwrite($params)", source)
        self.assertIn("favoriteservice::add($this->user,$params)", source)
        self.assertIn("favoriteservice::cancel($this->user,$params)", source)
        for forbidden in ("$params['user_id']", "$params['user']=", "system_user", "favorite_id"):
            self.assertNotIn(forbidden, source)

    def test_favorite_code_has_no_inquiry_or_event_side_effects(self) -> None:
        sources = "\n".join(
            read_utf8(path).lower()
            for path in (SERVICE_FILE, WEB_CONTROLLER_FILE, API_CONTROLLER_FILE, JS_FILE)
        )
        for forbidden in (
            "inquiry",
            "inquire",
            "询价",
            "myeventtrigger",
            "eventservice",
            "behavior",
            "analytics",
        ):
            self.assertNotIn(forbidden, sources)


class FavoriteRoutePolicyTests(unittest.TestCase):
    def test_old_write_actions_and_physical_goods_delete_are_denied(self) -> None:
        source = compact_code(read_utf8(POLICY_FILE))
        for token in (
            "publicconstweb_denied_actions=['goods'=>['favor'],'usergoodsfavor'=>['cancel','delete'],]",
            "publicconstapi_denied_actions=['goods'=>['favor'],'usergoodsfavor'=>['cancel','delete'],]",
            "publicconstadmin_denied_actions=['goods'=>['delete'],]",
        ):
            self.assertIn(token, source)
        action = method(POLICY_FILE, "IsActionDenied")
        self.assertIn("in_array($action,$map[$controller],true)", action)

    def test_safe_read_and_goods_update_actions_are_not_denied(self) -> None:
        source = compact_code(read_utf8(POLICY_FILE))
        denied_sections = source[source.index("publicconstweb_denied_actions") : source.index("publicconstdenied_plugins")]
        for allowed in ("statusupdate", "save", "detail", "index", "list"):
            self.assertNotIn("'" + allowed + "'", denied_sections)

    def test_system_begin_combines_controller_and_exact_action_guards(self) -> None:
        enforce = method(HOOK_FILE, "EnforceRequestScope")
        self.assertIn("$action=requestaction()", enforce)
        self.assertIn("scopepolicy::isrequestdenied($module,$controller,$plugins)", enforce)
        self.assertIn("scopepolicy::isactiondenied($module,$controller,$action)", enforce)
        self.assertEqual(enforce.count("abort(404"), 1)

    def test_admin_delete_permission_and_urls_are_filtered(self) -> None:
        power = method(POLICY_FILE, "FilterAdminPower")
        menu = method(POLICY_FILE, "FilterAdminMenu")
        shortcut = method(POLICY_FILE, "FilterShortcutMenu")
        self.assertIn("$normalized==='goods_delete'", power)
        self.assertIn("self::isactiondenied('admin',$control,$action)", menu)
        self.assertIn("urlcontainsdeniedadminaction", menu)
        self.assertIn("urlcontainsdeniedadminaction", shortcut)

    def test_goods_lists_get_one_batch_favorite_lookup_and_mobile_nav_is_rewired(self) -> None:
        handle = method(HOOK_FILE, "handle")
        mobile = method(HOOK_FILE, "ReplaceFavoriteBuyLeftNav")
        self.assertIn("plugins_service_goods_list_handle_begin", handle)
        self.assertIn("$params['params']['is_favor']=1", handle)
        self.assertIn("$item['type']='nursery-favorite'", mobile)
        self.assertIn("nursery-favorite-action", mobile)
        self.assertNotIn("common-goods-favor-submit-event", mobile)

    def test_config_registers_new_batch_and_mobile_hooks(self) -> None:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for hook in (
            "plugins_service_goods_list_handle_begin",
            "plugins_service_goods_buy_left_nav_handle",
        ):
            self.assertEqual(config["hook"][hook], [r"app\plugins\nursery\Hook"])


class FavoriteUiContractTests(unittest.TestCase):
    def test_cards_and_detail_use_only_explicit_nursery_actions(self) -> None:
        for path in (*CARD_VIEW_FILES, DETAIL_VIEW_FILE):
            source = read_utf8(path)
            self.assertIn("nursery-favorite-action", source)
            self.assertIn("data-add-url", source)
            self.assertIn("data-cancel-url", source)
            self.assertIn("data-csrf-token", source)
            self.assertNotIn("common-goods-favor-submit-event", source)
            self.assertNotIn("__goods_favor_url__", source)

    def test_my_favorites_shows_required_basic_fields_and_no_fake_inquiry(self) -> None:
        source = read_utf8(FAVORITE_VIEW_FILE)
        for token in (
            "我的收藏",
            "$item.images",
            "$item.title",
            "$item.reference_price.short_text",
            "$item.favorite_time_text",
            "$item.availability_text",
            "查看苗木",
            "取消收藏",
        ):
            self.assertIn(token, source)
        lowered = source.lower()
        for forbidden in ("询价", "inquiry", "购物车", "cart", "订单", "order"):
            self.assertNotIn(forbidden, lowered)

    def test_missing_or_unavailable_goods_do_not_get_a_detail_link_or_fake_price(self) -> None:
        source = read_utf8(FAVORITE_VIEW_FILE)
        self.assertIn("{{if !empty($item['goods_url'])}}", source)
        self.assertIn("暂不可查看", source)
        self.assertIn("当前无公开参考价", source)

    def test_js_chooses_target_state_and_locks_double_clicks(self) -> None:
        source = compact_code(read_utf8(JS_FILE))
        self.assertIn("varurl=active?button.attr('data-cancel-url'):button.attr('data-add-url')", source)
        self.assertIn("button.data('favorite-pending')===true", source)
        self.assertIn("data:{goods_id:goodsid,csrf_token:", source)
        self.assertIn("updatestate(goodsid,nextactive)", source)
        for forbidden in ("__goods_favor_url__", "data-toggle", "is_mandatory_favor"):
            self.assertNotIn(forbidden, source)

    def test_static_assets_are_project_local_and_responsive(self) -> None:
        css = read_utf8(CSS_FILE)
        self.assertIn("grid-template-columns", css)
        self.assertIn("@media only screen and (max-width: 640px)", css)
        self.assertNotIn("gradient", css.lower())
        for path in (*CARD_VIEW_FILES, DETAIL_VIEW_FILE, FAVORITE_VIEW_FILE):
            self.assertIn("StaticAttachmentUrl('favorite.js', 'js', 'nursery', 'index')", read_utf8(path))


class FavoriteScopeContractTests(unittest.TestCase):
    def test_business_diff_stays_inside_task_contract(self) -> None:
        commands = (
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            ["git", "diff", "--name-only"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        )
        paths: set[str] = set()
        for command in commands:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True)
            paths.update(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
        allowed_prefixes = (
            ".harness/tasks/NUR-FEAT-003/",
            "app/plugins/nursery/",
            "public/static/plugins/nursery/",
            "tests/nursery/",
        )
        allowed_files = {"scripts/nursery_favorite.php"}
        unexpected = sorted(
            path
            for path in paths
            if path not in allowed_files and not any(path.startswith(prefix) for prefix in allowed_prefixes)
        )
        self.assertEqual(unexpected, [])

    def test_shopxo_schema_and_core_favorite_service_are_unchanged(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                "origin/main",
                "--",
                "config/shopxo.sql",
                "app/service/GoodsFavorService.php",
                "app/index/controller/Goods.php",
                "app/api/controller/Usergoodsfavor.php",
                "app/admin/controller/Goods.php",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
