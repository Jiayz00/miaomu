import json
import re
import unittest
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "app" / "plugins" / "nursery" / "catalog-v1.json"
SEED_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$", re.ASCII)
CM_VALUE_PATTERN = re.compile(
    r"^(?P<minimum>[0-9]+(?:\.[0-9]+)?)(?:-(?P<maximum>[0-9]+(?:\.[0-9]+)?))?$",
    re.ASCII,
)

CATEGORY_FIELDS = {
    "seed_key",
    "parent_seed_key",
    "name",
    "vice_name",
    "describe",
    "sort",
    "is_home_recommended",
    "is_enable",
    "seo_title",
    "seo_keywords",
    "seo_desc",
}
SPEC_TEMPLATE_FIELDS = {
    "seed_key",
    "category_seed_key",
    "name",
    "values",
    "is_enable",
}
PARAMETER_FIELD_FIELDS = {"key", "name", "scope", "required", "data_type", "value"}
PARAMETER_TEMPLATE_FIELDS = {"seed_key", "category_seed_key", "name", "is_enable"}

EXPECTED_CATEGORY_TREE = {
    "乔木": {"常绿乔木", "落叶乔木", "观花与彩叶乔木"},
    "灌木": {"常绿灌木", "落叶与花灌木", "色块与绿篱苗"},
    "造型与盆景": {"造型树", "造型灌木", "桩景盆景"},
    "藤本与攀援": {"常绿藤本", "落叶藤本", "观花藤本"},
    "地被与草本": {"地被植物", "宿根花卉", "观赏草", "草坪"},
    "竹类": {"散生竹", "丛生竹", "观赏小竹"},
    "水生与湿生": {"挺水植物", "浮叶植物", "沉水植物", "湿生植物"},
    "果树与经济苗": {"果树苗", "坚果苗", "茶桑及其他经济苗"},
}

EXPECTED_PARAMETER_FIELDS = {
    "中文名",
    "学名",
    "科属",
    "苗龄",
    "常绿或落叶",
    "花期",
    "果期",
    "光照要求",
    "土壤要求",
    "耐寒性",
    "耐旱性",
    "适生地区",
    "园林用途",
    "栽植季节",
    "养护难度",
}

PRICE_DISCLAIMER = (
    "页面所示价格为参考价格，实际交易条件可能因规格、数量、库存、运输距离、"
    "装卸方式、栽植服务及市场变化而调整，最终以双方确认结果为准。"
)


def reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_manifest():
    return json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


class CatalogManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_manifest()
        cls.categories = cls.manifest["categories"]
        cls.categories_by_seed = {item["seed_key"]: item for item in cls.categories}
        cls.root_categories = [item for item in cls.categories if item["parent_seed_key"] is None]

    def test_manifest_versions_and_settings(self):
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["catalog_version"], 1)
        self.assertEqual(
            set(self.manifest),
            {
                "schema_version",
                "catalog_version",
                "settings",
                "categories",
                "spec_templates",
                "parameter_fields",
                "parameter_templates",
            },
        )
        self.assertEqual(
            self.manifest["settings"],
            {
                "max_category_depth": 2,
                "max_spec_dimensions": 2,
                "inventory_units": ["株", "盆", "丛", "平方米"],
                "price_disclaimer": PRICE_DISCLAIMER,
            },
        )

    def test_all_entity_seed_keys_are_stable_and_unique(self):
        entities = (
            self.manifest["categories"]
            + self.manifest["spec_templates"]
            + self.manifest["parameter_templates"]
        )
        seed_keys = [item["seed_key"] for item in entities]
        self.assertEqual(len(seed_keys), len(set(seed_keys)))
        for seed_key in seed_keys:
            self.assertRegex(seed_key, SEED_KEY_PATTERN)

    def test_category_tree_matches_the_approved_baseline(self):
        self.assertEqual(len(self.root_categories), 8)
        self.assertEqual(
            {item["name"] for item in self.root_categories},
            set(EXPECTED_CATEGORY_TREE),
        )

        children_by_parent = defaultdict(list)
        actual_tree = defaultdict(set)
        for item in self.categories:
            self.assertEqual(set(item), CATEGORY_FIELDS)
            self.assertIn(item["is_home_recommended"], {0, 1})
            self.assertIn(item["is_enable"], {0, 1})
            self.assertIsInstance(item["sort"], int)
            parent_seed_key = item["parent_seed_key"]
            if parent_seed_key is None:
                continue
            self.assertIn(parent_seed_key, self.categories_by_seed)
            children_by_parent[parent_seed_key].append(item["seed_key"])
            actual_tree[self.categories_by_seed[parent_seed_key]["name"]].add(item["name"])

        self.assertEqual(dict(actual_tree), EXPECTED_CATEGORY_TREE)
        self.assertEqual(len(self.categories), 34)

        for item in self.categories:
            parent_seed_key = item["parent_seed_key"]
            if parent_seed_key is None:
                self.assertIn(item["seed_key"], children_by_parent)
            else:
                parent = self.categories_by_seed[parent_seed_key]
                self.assertIsNone(parent["parent_seed_key"])
                self.assertNotIn(item["seed_key"], children_by_parent)

    def test_category_keys_and_sibling_names_are_unique(self):
        category_seed_keys = [item["seed_key"] for item in self.categories]
        self.assertEqual(len(category_seed_keys), len(set(category_seed_keys)))
        sibling_names = Counter(
            (item["parent_seed_key"], item["name"]) for item in self.categories
        )
        self.assertTrue(all(count == 1 for count in sibling_names.values()))

    def test_each_root_has_no_more_than_two_spec_templates(self):
        root_seed_keys = {item["seed_key"] for item in self.root_categories}
        specs_by_category = defaultdict(list)
        for template in self.manifest["spec_templates"]:
            self.assertEqual(set(template), SPEC_TEMPLATE_FIELDS)
            category_seed_key = template["category_seed_key"]
            self.assertIn(category_seed_key, root_seed_keys)
            specs_by_category[category_seed_key].append(template)
            self.assertIn(template["is_enable"], {0, 1})
            self.assertTrue(template["values"])
            self.assertEqual(len(template["values"]), len(set(template["values"])))

        self.assertEqual(set(specs_by_category), root_seed_keys)
        for templates in specs_by_category.values():
            self.assertGreaterEqual(len(templates), 1)
            self.assertLessEqual(
                len(templates), self.manifest["settings"]["max_spec_dimensions"]
            )

    def test_cm_spec_values_are_positive_single_values_or_closed_ranges(self):
        cm_templates = [
            item for item in self.manifest["spec_templates"] if item["name"].endswith("(cm)")
        ]
        self.assertTrue(cm_templates)
        for template in cm_templates:
            for value in template["values"]:
                self.assertIsInstance(value, str)
                match = CM_VALUE_PATTERN.fullmatch(value)
                self.assertIsNotNone(match, f"invalid cm value: {value}")
                try:
                    minimum = Decimal(match.group("minimum"))
                    maximum = Decimal(match.group("maximum") or match.group("minimum"))
                except InvalidOperation as exc:
                    self.fail(f"invalid cm decimal {value}: {exc}")
                self.assertGreater(minimum, Decimal("0"))
                self.assertGreaterEqual(maximum, minimum)

    def test_global_parameter_fields_match_the_requirements(self):
        fields = self.manifest["parameter_fields"]
        self.assertEqual({item["name"] for item in fields}, EXPECTED_PARAMETER_FIELDS)
        self.assertEqual(len(fields), len(EXPECTED_PARAMETER_FIELDS))

        keys = [item["key"] for item in fields]
        self.assertEqual(len(keys), len(set(keys)))
        for field in fields:
            self.assertEqual(set(field), PARAMETER_FIELD_FIELDS)
            self.assertRegex(field["key"], SEED_KEY_PATTERN)
            self.assertIn(field["scope"], {0, 1, 2})
            self.assertIn(field["required"], {0, 1})
            self.assertIn(field["data_type"], {0, 1, 2})
            self.assertIsInstance(field["value"], str)
            if field["data_type"] == 0:
                self.assertEqual(field["value"], "")
            else:
                values = field["value"].splitlines()
                self.assertTrue(values)
                self.assertEqual(len(values), len(set(values)))
                self.assertTrue(all(values))

    def test_all_roots_declare_a_parameter_template(self):
        templates = self.manifest["parameter_templates"]
        root_seed_keys = {item["seed_key"] for item in self.root_categories}
        self.assertEqual(len(templates), 8)
        self.assertEqual(
            {item["category_seed_key"] for item in templates},
            root_seed_keys,
        )
        for template in templates:
            self.assertEqual(set(template), PARAMETER_TEMPLATE_FIELDS)
            self.assertTrue(template["name"])
            self.assertIn(template["is_enable"], {0, 1})


if __name__ == "__main__":
    unittest.main()
