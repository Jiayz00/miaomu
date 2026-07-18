from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "app" / "plugins" / "nursery"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class SecuritySchemaContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(read(PLUGIN / "security-schema-v1.json"))
        self.migration = read(PLUGIN / "service" / "SecurityMigration.php")

    def test_manifest_pins_two_tables_and_ledger(self) -> None:
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["security_schema_version"], 1)
        self.assertEqual(
            list(self.manifest["tables"]), ["favorite_rate_limit", "goods_audit"]
        )
        rate = self.manifest["tables"]["favorite_rate_limit"]
        self.assertEqual(rate["logical_name"], "PluginsNurseryFavoriteRateLimit")
        self.assertEqual(
            [item["name"] for item in rate["indexes"]],
            ["PRIMARY", "idx_nursery_favorite_rate_updated"],
        )
        self.assertEqual(rate["indexes"][0]["columns"], ["user_id", "action"])
        audit = self.manifest["tables"]["goods_audit"]
        self.assertEqual(audit["logical_name"], "PluginsNurseryGoodsAudit")
        self.assertEqual(
            {item["name"] for item in audit["indexes"]},
            {
                "PRIMARY",
                "idx_nursery_goods_audit_goods_time",
                "idx_nursery_goods_audit_admin_time",
                "idx_nursery_goods_audit_request",
            },
        )
        self.assertEqual(
            self.manifest["ledger"]["only_tag"], "plugins_nursery_security_schema_v1"
        )

    def test_migration_is_forward_only_locked_and_fail_closed(self) -> None:
        for token in (
            "GET_LOCK",
            "RELEASE_LOCK",
            "information_schema",
            "CreateMissingIndexes",
            "AssertReady",
            "payload_sha256",
            "replayed",
        ):
            self.assertIn(token, self.migration)
        self.assertNotRegex(self.migration, r"\b(?:DROP|TRUNCATE|DELETE)\s+", re.I)
        self.assertIn("same-name table", self.migration)


class FavoriteRateLimitContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rate = read(PLUGIN / "service" / "FavoriteRateLimit.php")
        self.favorite = read(PLUGIN / "service" / "FavoriteService.php")

    def test_actions_are_independent_fixed_window_and_row_locked(self) -> None:
        self.assertIn("public const WINDOW_SECONDS = 60", self.rate)
        self.assertIn("public const MAX_ATTEMPTS = 20", self.rate)
        self.assertIn("['add', 'cancel']", self.rate)
        self.assertIn("->lock(true)", self.rate)
        self.assertIn("Db::startTrans()", self.rate)
        self.assertIn("Db::commit()", self.rate)
        self.assertIn("Db::rollback()", self.rate)
        self.assertIn("UNIX_TIMESTAMP", self.rate)
        self.assertIn("SecurityMigration::AssertReady()", self.rate)
        self.assertIn("$count < 1 || $count > self::MAX_ATTEMPTS", self.rate)
        self.assertIn("$now < $started_at", self.rate)
        self.assertIn("收藏频率限制状态无效", self.rate)
        self.assertIn("FavoriteRateLimit::Consume($user_id, 'add')", self.favorite)
        self.assertIn("FavoriteRateLimit::Consume($user_id, 'cancel')", self.favorite)

    def test_counter_does_not_use_ip_or_personal_fields(self) -> None:
        lowered = self.rate.lower()
        for forbidden in ("remote_addr", "phone", "mobile", "request_body", "contact_phone"):
            self.assertNotIn(forbidden, lowered)


class ProductAuditContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = read(PLUGIN / "service" / "GoodsAuditService.php")
        self.hook = read(PLUGIN / "Hook.php")
        self.core = read(ROOT / "app" / "service" / "GoodsService.php")
        self.config = json.loads(read(PLUGIN / "config.json"))["hook"]

    def test_price_and_shelf_audit_is_append_only_and_transaction_bound(self) -> None:
        for token in (
            "PrepareSave",
            "CommitSave",
            "RecordStatus",
            "price_update",
            "shelf_update",
            "old_value",
            "new_value",
            "request_id",
            "insertGetId",
        ):
            self.assertIn(token, self.audit)
        self.assertIn("plugins_service_goods_save_thing_begin", self.hook)
        self.assertIn("plugins_service_goods_save_thing_end", self.hook)
        self.assertIn("GoodsAuditService::CommitSave", self.hook)
        self.assertIn("GoodsAuditService::RecordStatus", self.hook)
        self.assertIn("previous_goods", self.core)
        self.assertIn("->lock(true)", self.core)
        self.assertIn("SecurityMigration::AssertReady()", self.audit)
        self.assertIn("self::$pending_save = []", self.audit)
        self.assertNotRegex(self.audit, r"->(?:delete|update)\(", re.I)

    def test_manifest_registers_all_audit_hooks(self) -> None:
        for hook in (
            "plugins_service_goods_save_thing_begin",
            "plugins_service_goods_save_thing_end",
            "plugins_service_goods_field_status_update",
            "plugins_service_goods_handle_end",
            "plugins_service_search_goods_list_begin",
        ):
            self.assertIn(hook, self.config)


class NurseryDisplayContractTests(unittest.TestCase):
    def test_list_and_favorite_views_expose_spec_and_origin(self) -> None:
        for relative in (
            "view/index/module/goods/grid/base.html",
            "view/index/module/goods/list/base.html",
            "view/index/module/goods/slider/binding.html",
            "view/index/favorite/index.html",
        ):
            source = read(PLUGIN / relative)
            self.assertIn("primary_spec_text", source, relative)
            self.assertIn("produce_region_name", source, relative)

        favorite_service = read(PLUGIN / "service" / "FavoriteService.php")
        self.assertIn("GoodsService::GoodsSpecificationsData", favorite_service)
        self.assertNotIn("Db::name('GoodsSpecType')", favorite_service)

    def test_off_shelf_detail_does_not_render_inquiry_cta(self) -> None:
        source = read(
            PLUGIN / "view/index/goods/module/middle_base/left/photo_pc_bottom_favor.html"
        )
        self.assertIn("is_shelves", source)
        self.assertIn("is_delete_time", source)
        self.assertIn("nursery-inquiry-detail-entry", source)

    def test_display_adapter_uses_processed_specifications(self) -> None:
        source = read(PLUGIN / "service/GoodsDisplayService.php")
        self.assertIn("specifications", source)
        self.assertIn("primary_spec_text", source)
        self.assertNotIn("Db::name", source)


class CoreBoundaryContractTests(unittest.TestCase):
    def test_only_registered_goods_status_hook_core_change_is_present(self) -> None:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "--", "app/service"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        changed = [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
        self.assertIn("app/service/GoodsService.php", changed)
        self.assertEqual(changed, ["app/service/GoodsService.php"])


if __name__ == "__main__":
    unittest.main()
