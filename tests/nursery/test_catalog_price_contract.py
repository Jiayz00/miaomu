from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

from test_catalog_manifest import CatalogManifestTest  # noqa: F401
from test_scope_contract import (
    ContractError,
    EXPECTED_GOODS_VIEW_HOOKS,
    FORBIDDEN_GOODS_CART_MARKERS,
    ROOT,
    compact_code,
    extract_php_method,
    read_utf8,
    require,
)


PLUGIN_ROOT = ROOT / "app" / "plugins" / "nursery"
CONFIG_FILE = PLUGIN_ROOT / "config.json"
EVENT_FILE = PLUGIN_ROOT / "Event.php"
HOOK_FILE = PLUGIN_ROOT / "Hook.php"
CATALOG_POLICY_FILE = PLUGIN_ROOT / "service" / "CatalogPolicy.php"
PRICE_SERVICE_FILE = PLUGIN_ROOT / "service" / "ReferencePriceService.php"
MIGRATION_FILE = PLUGIN_ROOT / "service" / "CatalogMigration.php"
INTEGRITY_FILE = PLUGIN_ROOT / "service" / "CatalogIntegrity.php"
CLI_FILE = ROOT / "scripts" / "nursery_catalog.php"
GRID_VIEW_FILE = PLUGIN_ROOT / "view" / "index" / "module" / "goods" / "grid" / "base.html"
UPSTREAM_GRID_VIEW_FILE = ROOT / "app" / "index" / "view" / "default" / "module" / "goods" / "grid" / "base.html"

EXPECTED_PRICE_HOOKS = {
    "plugins_service_goods_save_handle",
    "plugins_service_goods_save_thing_end",
    "plugins_service_goods_field_status_update",
    "plugins_service_goods_handle_begin",
    "plugins_view_goods_detail_panel_price_bottom",
}
DISCLAIMER = (
    "页面所示价格为参考价格，实际交易条件可能因规格、数量、库存、运输距离、"
    "装卸方式、栽植服务及市场变化而调整，最终以双方确认结果为准。"
)


class PriceHookContractTests(unittest.TestCase):
    def test_manifest_registers_exact_price_hooks(self) -> None:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        hooks = config["hook"]
        self.assertTrue(EXPECTED_PRICE_HOOKS.issubset(hooks))
        for hook in EXPECTED_PRICE_HOOKS:
            self.assertEqual(hooks[hook], [r"app\plugins\nursery\Hook"])

    def test_hook_routes_save_status_display_and_disclaimer(self) -> None:
        source = read_utf8(HOOK_FILE)
        handle = compact_code(extract_php_method(source, "handle"))
        required = (
            "referencepriceservice::validatesave($params['params'],$params['data'],$params['spec'])",
            "plugins_service_goods_save_thing_end",
            "intval($params['data']['is_shelves'])===1",
            "$params['field']==='is_shelves'",
            "intval($params['status'])===1",
            "referencepriceservice::assertpublishedgoods(",
            "referencepriceservice::applydisplay($params['goods'])",
            "referencepriceservice::disclaimerhtml()",
        )
        for token in required:
            self.assertIn(token, handle)
        status_branch = handle[handle.index("plugins_service_goods_field_status_update") :]
        self.assertNotIn("datareturn(", status_branch.split("plugins_service_goods_handle_begin", 1)[0])

    def test_begin_install_and_upgrade_are_read_only_preflight(self) -> None:
        source = read_utf8(EVENT_FILE)
        for method in ("BeginInstall", "BeginUpgrade"):
            body = compact_code(extract_php_method(source, method))
            self.assertIn("catalogmigration::preflight(", body)
            self.assertNotIn("catalogmigration::run(", body)
            self.assertNotIn("db::", body)


class ReferencePriceServiceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read_utf8(PRICE_SERVICE_FILE)
        cls.compact = compact_code(cls.source)

    def test_input_price_is_full_ascii_decimal_and_normalized(self) -> None:
        self.assertIn("/^[0-9]{1,8}(\\.[0-9]{1,2})?$/D", self.source)
        method = compact_code(extract_php_method(self.source, "NormalizeInputPrice"))
        self.assertIn("!is_string($value)", method)
        self.assertIn("preg_match(self::price_pattern,$value)!==1", method)
        self.assertIn("self::formatcents($cents)", method)
        for forbidden in ("is_numeric(", "floatval(", "doubleval(", "filter_var("):
            self.assertNotIn(forbidden, method)

    def test_save_gate_distinguishes_draft_and_published_rows(self) -> None:
        method = compact_code(extract_php_method(self.source, "ValidateSave"))
        required = (
            "catalogpolicy::validatesave($params,$spec)",
            "$data['inventory_unit']=$params['inventory_unit']",
            "$is_shelves=isset($data['is_shelves'])&&intval($data['is_shelves'])===1",
            "goodsservice::goodsspecbasefields()",
            "array_search('price',$base_fields,true)",
            "($is_shelves&&$cents<1)",
            "$params['specifications_price'][$index]=$normalized",
            "$spec['data'][$index][$base_start+$price_offset]=$normalized",
        )
        for token in required:
            self.assertIn(token, method)
        self.assertIn("0.01 至 99999999.99", self.source)
        self.assertIn("0.00 至 99999999.99", self.source)

    def test_independent_publish_check_throws_and_verifies_aggregate(self) -> None:
        method = compact_code(extract_php_method(self.source, "AssertPublishedGoods"))
        for token in (
            "catalogpolicy::publishedgoodserror(",
            "db::name('goodsspecbase')",
            "thrownew\\runtimeexception(",
            "$min_price!==$min",
            "$max_price!==$max",
            "(string)$goods['price']!==$expected_price",
        ):
            self.assertIn(token, method)
        self.assertNotIn("return datareturn(", method)

    def test_display_model_is_public_fixed_or_range(self) -> None:
        method = compact_code(extract_php_method(self.source, "ApplyDisplay"))
        for token in (
            "$mode=($min===$max)?'fixed':'range'",
            "$goods['show_field_price_status']=1",
            "$goods['show_field_price_text']='参考价'",
            "$goods['reference_price']=[",
            "'short_text'=>$short_text",
            "'disclaimer'=>self::disclaimer",
        ):
            self.assertIn(token, method)
        self.assertIn("' 起'", self.source)
        self.assertIn(DISCLAIMER, self.source)


class CatalogPolicyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read_utf8(CATALOG_POLICY_FILE)
        cls.compact = compact_code(cls.source)

    def test_policy_uses_manifest_ledger_managed_leaf_ids(self) -> None:
        for token in (
            "plugins_nursery_catalog_manifest",
            "catalog-v1.json",
            "publicstaticfunctionmanagedleafids()",
            "$ledger['entities'][$seed_key]['id']",
            "$ledger['entities'][$seed_key]['type']!=='category'",
        ):
            self.assertIn(token, self.compact)

    def test_save_rejects_multiple_unmanaged_disabled_or_nonleaf_categories(self) -> None:
        validate = compact_code(extract_php_method(self.source, "ValidateSave"))
        published = compact_code(extract_php_method(self.source, "PublishedGoodsError"))
        managed = compact_code(extract_php_method(self.source, "ManagedLeafError"))
        strict_id = compact_code(extract_php_method(self.source, "StrictSingleId"))
        self.assertIn("self::strictsingleid(", validate)
        self.assertIn("count($value)!==1", strict_id)
        self.assertIn("intval($item)<=0", strict_id)
        self.assertIn("count($category_rows)!==1", published)
        self.assertIn("$managed=self::managedleafmap()", managed)
        self.assertIn("!isset($managed[$category_id])", managed)
        self.assertIn("intval($category['pid'])!==$expected_parent_id", managed)
        self.assertIn("self::normalizename($category['name'])!==self::normalizename($definition['name'])", managed)
        self.assertIn("intval($category['is_enable'])!==1", managed)
        self.assertIn("intval($parent['pid'])!==0", managed)
        self.assertIn("self::normalizename($parent['name'])!==self::normalizename($definitions[$parent_key]['name'])", managed)
        self.assertIn("where(['pid'=>intval($category_id),'is_enable'=>1])->count()>0", managed)

    def test_runtime_ledger_requires_current_payload_and_parent_structure(self) -> None:
        ledger = compact_code(extract_php_method(self.source, "Ledger"))
        managed = compact_code(extract_php_method(self.source, "ManagedLeafError"))
        self.assertIn("$ledger['manifest_schema_version']", ledger)
        self.assertIn("$ledger['catalog_version']", ledger)
        self.assertIn("hash_equals($ledger['payload_sha256'],$expected_payload_hash)", ledger)
        self.assertIn("$ledger['entities'][$parent_key]['structure_sha256']", managed)

    def test_dimensions_and_units_come_from_project_manifest(self) -> None:
        validate = compact_code(extract_php_method(self.source, "ValidateSave"))
        shape = compact_code(extract_php_method(self.source, "ValidateSpecificationShape"))
        published = compact_code(extract_php_method(self.source, "PublishedGoodsError"))
        self.assertIn("$definition['settings']['max_spec_dimensions']", validate)
        self.assertIn("goodsservice::goodsspecbasefields()", shape)
        self.assertIn("$ordered_data_keys!==array_merge($dimension_keys,$base_keys)", shape)
        self.assertIn("$title_dimensions!==$dimensions", shape)
        self.assertIn("count($row)!==$dimensions+$base_count", shape)
        self.assertIn("self::inventoryunits()", validate)
        self.assertIn("$params['specifications_inventory_unit'][$index]=$spec_unit", shape)
        self.assertIn("$row[$dimensions+$inventory_offset]=$spec_unit", shape)
        self.assertIn("db::name('goodsspectype')", published)
        self.assertIn("db::name('goodsspecbase')", published)
        self.assertIn("column('inventory_unit')", published)
        self.assertNotRegex(self.source, r"const\s+INVENTORY_UNITS")


class CatalogMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read_utf8(MIGRATION_FILE)
        cls.compact = compact_code(cls.source)

    def test_preflight_is_read_only(self) -> None:
        method = compact_code(extract_php_method(self.source, "Preflight"))
        for forbidden in ("db::starttrans(", "importdefinition(", "writeledger(", "->insert", "->update("):
            self.assertNotIn(forbidden, method)
        self.assertIn("verif yledger(".replace(" ", ""), method)
        self.assertIn("write_performed'=>false", method)

    def test_run_requires_metadata_and_atomic_locked_ledger(self) -> None:
        method = compact_code(extract_php_method(self.source, "Run"))
        for token in (
            "self::validateexecutionmetadata($actor,$run_id)",
            "self::acquireexecutionlock()",
            "$lock_connection->starttrans()",
            "->lock(true)",
            "self::importdefinition(",
            "self::verifyledger(",
            "self::writeledger(",
            "$lock_connection->commit()",
            "$lock_connection->rollback()",
            "self::releaseexecutionlock(",
        ):
            self.assertIn(token, method)
        acquire = compact_code(extract_php_method(self.source, "AcquireExecutionLock"))
        release = compact_code(extract_php_method(self.source, "ReleaseExecutionLock"))
        self.assertIn("db::connect()", acquire)
        self.assertIn("[],true", acquire)
        self.assertIn("[],true", release)
        self.assertIn("intval($rows[0]['released'])!==1", release)

    def test_existing_ledger_rejects_unmanaged_duplicates_and_parameter_drift(self) -> None:
        verify = compact_code(extract_php_method(self.source, "VerifyLedger"))
        parameter_hash = compact_code(extract_php_method(self.source, "ParameterStructureHash"))
        self.assertEqual(verify.count("self::assertmanagedsiblingunique("), 3)
        self.assertIn("field('id,category_id,name,config_count')", verify)
        self.assertIn("count($configs)!==count($definition['parameter_fields'])", verify)
        self.assertIn("intval($config['scope'])!==intval($field['scope'])", verify)
        self.assertIn("intval($config['required'])!==", verify)
        self.assertIn("'scope'=>intval($field['scope'])", parameter_hash)
        self.assertIn("'required'=>empty($field['required'])?0:1", parameter_hash)

    def test_runtime_manifest_rejects_nonpositive_or_reversed_cm_ranges(self) -> None:
        validate = compact_code(extract_php_method(self.source, "ValidateDefinition"))
        self.assertIn("$minimum<=0||$maximum<$minimum", validate)
        self.assertIn("苗木厘米规格值必须为正数单值或闭区间", self.source)

    def test_structure_hash_excludes_operational_category_fields(self) -> None:
        method = compact_code(extract_php_method(self.source, "CategoryStructureHash"))
        for token in ("'seed_key'", "'parent_seed_key'", "'name'"):
            self.assertIn(token, method)
        for forbidden in ("sort", "icon", "describe", "seo_", "is_enable"):
            self.assertNotIn(forbidden, method)

    def test_import_has_conflict_idempotency_and_no_goods_mutation(self) -> None:
        self.assertIn("AssertSiblingNameAvailable", self.source)
        self.assertIn("苗木目录清单内容已变化但 catalog_version 未升级", self.source)
        self.assertIn("FindRun", self.source)
        run = compact_code(extract_php_method(self.source, "Run"))
        find_run = compact_code(extract_php_method(self.source, "FindRun"))
        sibling_available = compact_code(extract_php_method(self.source, "AssertSiblingNameAvailable"))
        sibling_unique = compact_code(extract_php_method(self.source, "AssertManagedSiblingUnique"))
        self.assertIn("(string)$previous_run['actor']!==$actor", run)
        self.assertIn("(string)$previous_run['mode']!==$mode", run)
        self.assertIn("array_reverse($ledger['runs'])", find_run)
        self.assertIn("$query=$query->lock(true)", sibling_available)
        self.assertIn("$query=$query->lock(true)", sibling_unique)
        self.assertIn("self::assertinitialrootnamesavailable($definition,true)", run)
        self.assertIn("self::verifyledger($definition,$ledger,true)", run)
        lowered = self.source.lower()
        self.assertNotIn("db::name('goods')->", lowered)
        self.assertNotIn("goodscategoryjoin", lowered)
        self.assertNotIn("->delete(", lowered)


class IntegrityAndCliContractTests(unittest.TestCase):
    def test_integrity_defaults_to_dry_run_and_apply_is_audited(self) -> None:
        source = read_utf8(INTEGRITY_FILE)
        run = compact_code(extract_php_method(source, "Run"))
        analyze = compact_code(extract_php_method(source, "AnalyzePublishedGoods"))
        self.assertIn("functionrun($apply=false,$actor='',$run_id='',$expected_items_sha256='')", run)
        self.assertIn("'write_performed'=>false", run)
        self.assertLess(run.index("if($apply!==true)"), run.index("$lock_connection->starttrans()"))
        for token in (
            "self::validateexecutionmetadata($actor,$run_id)",
            "plugins_nursery_catalog_integrity_log",
            "'before'",
            "'after'",
            "'actor'=>$actor",
            "'run_id'=>$run_id",
            "$lock_connection->rollback()",
            "self::acquireexecutionlock()",
            "self::releaseexecutionlock(",
            "self::itemshash($items)",
            "hash_equals($expected_items_sha256,$reviewed_hash)",
        ):
            self.assertIn(token, compact_code(source))
        self.assertNotIn("db::name('goodsspecbase')->where", compact_code(extract_php_method(source, "WriteAudit")))
        self.assertNotIn("->delete(", source.lower())
        self.assertIn("where(['is_shelves'=>1,'is_delete_time'=>0])", analyze)
        self.assertIn("count($items)>self::max_review_items", run)
        self.assertIn("'upd_time'=>intval($item['upd_time'])", analyze)
        self.assertIn("$audit['history'][]=$run_summary", run)
        self.assertIn("self::findrun($audit,$run_id)", run)
        self.assertIn("(string)$previous_run['actor']!==$actor", run)
        self.assertIn("hash_equals((string)$previous_run['reviewed_items_sha256'],$expected_items_sha256)", run)

    def test_cli_has_locked_actions_and_explicit_write_flags(self) -> None:
        source = read_utf8(CLI_FILE)
        compact = compact_code(source)
        for token in (
            "['preflight','migrate','integrity']",
            "migraterequires--",
            "integrity--applyrequires--actor,--run-id,and--expected-items-sha256",
            "catalogmigration::run(",
            "catalogintegrity::run($apply",
            "json_encode(",
            "exit(isset($result['code'])",
            "(newapp($root))->initialize()",
            "catch(\\throwable$e)",
        ):
            self.assertIn(token, compact)
        for forbidden in ("shell_exec(", "exec(", "system(", "passthru(", "curl", "ssh ", "scp "):
            self.assertNotIn(forbidden, source.lower())

    def test_event_never_calls_integrity_apply_or_write_migration(self) -> None:
        event = compact_code(read_utf8(EVENT_FILE))
        self.assertNotIn("catalogintegrity::", event)
        self.assertNotIn("catalogmigration::run(", event)


class PublicTemplateContractTests(unittest.TestCase):
    def test_grid_preserves_hooks_and_links_but_has_no_commerce_action(self) -> None:
        source = read_utf8(GRID_VIEW_FILE)
        upstream = read_utf8(UPSTREAM_GRID_VIEW_FILE)
        lowered = source.lower()
        for marker in FORBIDDEN_GOODS_CART_MARKERS:
            self.assertNotIn(marker, lowered)
        for marker in ("buy_title", "index/order/", "index/payment/", "checkout", "购物车", "立即购买"):
            self.assertNotIn(marker, lowered)
        self.assertIn("reference_price.short_text", source)
        self.assertIn("参考价", source)
        self.assertIn("查看详情", source)
        self.assertGreater(source.count("goods_url"), 0)
        for hook in EXPECTED_GOODS_VIEW_HOOKS:
            self.assertEqual(source.count(hook), upstream.count(hook))

    def test_business_diff_does_not_touch_shopxo_core_or_default_theme(self) -> None:
        changed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        paths = set(changed + untracked)
        forbidden_prefixes = (
            "app/service/",
            "app/admin/",
            "app/index/controller/",
            "app/index/view/default/",
            "app/api/",
            "config/shopxo.sql",
            "vendor/",
        )
        for path in paths:
            self.assertFalse(path.startswith(forbidden_prefixes), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
