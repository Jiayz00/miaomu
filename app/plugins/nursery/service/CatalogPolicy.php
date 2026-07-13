<?php
namespace app\plugins\nursery\service;

use app\service\GoodsService;
use think\facade\Db;

class CatalogPolicy
{
    public const MANIFEST_TAG = 'plugins_nursery_catalog_manifest';

    private static $definition = null;
    private static $ledger = null;

    public static function Definition()
    {
        if(self::$definition !== null)
        {
            return self::$definition;
        }
        $path = dirname(__DIR__).DIRECTORY_SEPARATOR.'catalog-v1.json';
        if(!is_file($path))
        {
            throw new \RuntimeException('苗木目录清单不存在');
        }
        $content = file_get_contents($path);
        $definition = ($content === false) ? null : json_decode($content, true);
        if(!is_array($definition) || empty($definition['categories']) || empty($definition['settings']['inventory_units']))
        {
            throw new \RuntimeException('苗木目录清单格式无效');
        }
        self::$definition = $definition;
        return self::$definition;
    }

    public static function Ledger()
    {
        if(self::$ledger !== null)
        {
            return self::$ledger;
        }
        $value = Db::name('Config')->where(['only_tag'=>self::MANIFEST_TAG])->value('value');
        $ledger = empty($value) ? null : json_decode($value, true);
        if(!is_array($ledger) || empty($ledger['entities']) || !is_array($ledger['entities']))
        {
            throw new \RuntimeException('苗木目录尚未通过受控迁移初始化');
        }
        $definition = self::Definition();
        $expected_payload_hash = hash('sha256', json_encode($definition, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));
        if(!isset($ledger['manifest_schema_version'], $ledger['catalog_version'], $ledger['payload_sha256']) ||
            intval($ledger['manifest_schema_version']) !== intval($definition['schema_version']) ||
            intval($ledger['catalog_version']) !== intval($definition['catalog_version']) ||
            !is_string($ledger['payload_sha256']) || !hash_equals($ledger['payload_sha256'], $expected_payload_hash))
        {
            throw new \RuntimeException('苗木目录台账版本或清单哈希无效');
        }
        self::$ledger = $ledger;
        return self::$ledger;
    }

    public static function ResetRuntimeCache()
    {
        self::$definition = null;
        self::$ledger = null;
    }

    public static function InventoryUnits()
    {
        $definition = self::Definition();
        return array_values(array_unique(array_filter(array_map('trim', $definition['settings']['inventory_units']))));
    }

    public static function ManagedLeafIds()
    {
        return array_keys(self::ManagedLeafMap());
    }

    private static function ManagedLeafMap()
    {
        $definition = self::Definition();
        $ledger = self::Ledger();
        $parent_keys = [];
        foreach($definition['categories'] as $category)
        {
            if(!empty($category['parent_seed_key']))
            {
                $parent_keys[$category['parent_seed_key']] = true;
            }
        }

        $items = [];
        foreach($definition['categories'] as $category)
        {
            $seed_key = isset($category['seed_key']) ? $category['seed_key'] : '';
            if($seed_key === '' || isset($parent_keys[$seed_key]))
            {
                continue;
            }
            if(!isset($ledger['entities'][$seed_key]['id'], $ledger['entities'][$seed_key]['type'], $ledger['entities'][$seed_key]['structure_sha256']) || $ledger['entities'][$seed_key]['type'] !== 'category')
            {
                throw new \RuntimeException('苗木目录台账缺少受管叶子：'.$seed_key);
            }
            $structure = [
                'type'            => 'category',
                'seed_key'        => $seed_key,
                'parent_seed_key' => empty($category['parent_seed_key']) ? null : $category['parent_seed_key'],
                'name'            => self::NormalizeName($category['name']),
            ];
            $expected_hash = hash('sha256', json_encode($structure, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));
            if(!hash_equals((string) $ledger['entities'][$seed_key]['structure_sha256'], $expected_hash))
            {
                throw new \RuntimeException('苗木目录台账叶子结构哈希无效：'.$seed_key);
            }
            $id = intval($ledger['entities'][$seed_key]['id']);
            if($id <= 0 || isset($items[$id]))
            {
                throw new \RuntimeException('苗木目录台账叶子 ID 无效或重复：'.$seed_key);
            }
            $items[$id] = [
                'definition' => $category,
                'entity'     => $ledger['entities'][$seed_key],
            ];
        }
        return $items;
    }

    public static function ValidateSave(&$params, &$spec)
    {
        $category_id = self::StrictSingleId(isset($params['category_id']) ? $params['category_id'] : null);
        if($category_id === null)
        {
            return '商品必须选择一个受管苗木叶子分类';
        }
        $error = self::ManagedLeafError($category_id);
        if($error !== null)
        {
            return $error;
        }

        $definition = self::Definition();
        $max_dimensions = intval($definition['settings']['max_spec_dimensions']);
        $unit = isset($params['inventory_unit']) && is_string($params['inventory_unit']) ? trim($params['inventory_unit']) : '';
        $units = self::InventoryUnits();
        if(!in_array($unit, $units, true))
        {
            return '库存单位必须是：'.implode('、', $units);
        }
        $params['inventory_unit'] = $unit;
        $shape_error = self::ValidateSpecificationShape($params, $spec, $max_dimensions, $units);
        if($shape_error !== null)
        {
            return $shape_error;
        }
        return null;
    }

    private static function ValidateSpecificationShape(&$params, &$spec, $max_dimensions, $units)
    {
        if(empty($spec['data']) || !is_array($spec['data']))
        {
            return '苗木商品规格行不能为空';
        }
        $base_fields = GoodsService::GoodsSpecBaseFields();
        $base_keys = array_map(function($field)
        {
            return 'specifications_'.$field;
        }, $base_fields);
        $dimension_keys = [];
        $ordered_data_keys = [];
        foreach($params as $key=>$value)
        {
            if(!is_string($key) || strpos($key, 'specifications_') !== 0)
            {
                continue;
            }
            if(strpos($key, 'specifications_name_') === 0)
            {
                continue;
            }
            if(strpos($key, 'specifications_value_') === 0)
            {
                if(!is_array($value))
                {
                    return '苗木商品规格维度值格式无效';
                }
                $dimension_keys[] = $key;
                $ordered_data_keys[] = $key;
                continue;
            }
            if(!in_array($key, $base_keys, true) || !is_array($value))
            {
                return '苗木商品规格包含未知或无效字段';
            }
            $ordered_data_keys[] = $key;
        }
        if($ordered_data_keys !== array_merge($dimension_keys, $base_keys))
        {
            return '苗木商品规格字段顺序与固定 ShopXO 基线不一致';
        }
        $dimensions = count($dimension_keys);
        if($dimensions > intval($max_dimensions))
        {
            return '苗木商品规格维度不得超过'.intval($max_dimensions).'个';
        }
        $title_dimensions = (isset($spec['title']) && is_array($spec['title'])) ? count($spec['title']) : 0;
        if($title_dimensions !== $dimensions)
        {
            return '苗木商品规格维度定义与规格行不一致';
        }

        $row_keys = array_keys($spec['data']);
        foreach(array_merge($dimension_keys, $base_keys) as $key)
        {
            if(!isset($params[$key]) || !is_array($params[$key]) || array_keys($params[$key]) !== $row_keys)
            {
                return '苗木商品规格字段与规格行数量不一致';
            }
        }
        $base_count = count($base_fields);
        $inventory_offset = array_search('inventory_unit', $base_fields, true);
        foreach($spec['data'] as $index=>&$row)
        {
            if(!is_array($row) || count($row) !== $dimensions+$base_count)
            {
                return '苗木商品规格行结构无效';
            }
            $spec_unit = $params['specifications_inventory_unit'][$index];
            if(!is_string($spec_unit))
            {
                return '规格库存单位格式无效';
            }
            $spec_unit = trim($spec_unit);
            if($spec_unit !== '' && !in_array($spec_unit, $units, true))
            {
                return '规格库存单位必须是：'.implode('、', $units);
            }
            $params['specifications_inventory_unit'][$index] = $spec_unit;
            $row[$dimensions+$inventory_offset] = $spec_unit;
        }
        unset($row);
        return null;
    }

    public static function PublishedGoodsError($goods_id, $inventory_unit)
    {
        $category_rows = Db::name('GoodsCategoryJoin')->where(['goods_id'=>intval($goods_id)])->column('category_id');
        if(count($category_rows) !== 1 || !is_scalar($category_rows[0]) || preg_match('/^[0-9]+$/D', trim((string) $category_rows[0])) !== 1 || intval($category_rows[0]) <= 0)
        {
            return '商品必须关联一个受管苗木叶子分类';
        }
        $error = self::ManagedLeafError(intval($category_rows[0]));
        if($error !== null)
        {
            return $error;
        }
        if(!is_string($inventory_unit) || !in_array(trim($inventory_unit), self::InventoryUnits(), true))
        {
            return '商品库存单位不在苗木单位白名单';
        }
        $definition = self::Definition();
        $max_dimensions = intval($definition['settings']['max_spec_dimensions']);
        if(Db::name('GoodsSpecType')->where(['goods_id'=>intval($goods_id)])->count() > $max_dimensions)
        {
            return '苗木商品规格维度不得超过'.$max_dimensions.'个';
        }
        $units = self::InventoryUnits();
        $spec_units = Db::name('GoodsSpecBase')->where(['goods_id'=>intval($goods_id)])->column('inventory_unit');
        foreach($spec_units as $spec_unit)
        {
            $spec_unit = trim((string) $spec_unit);
            if($spec_unit !== '' && !in_array($spec_unit, $units, true))
            {
                return '商品规格库存单位不在苗木单位白名单';
            }
        }
        return null;
    }

    private static function ManagedLeafError($category_id)
    {
        $managed = self::ManagedLeafMap();
        $category_id = intval($category_id);
        if(!isset($managed[$category_id]))
        {
            return '所选分类不是当前目录台账中的受管苗木叶子分类';
        }
        $definition = $managed[$category_id]['definition'];
        $parent_key = isset($definition['parent_seed_key']) ? $definition['parent_seed_key'] : null;
        $ledger = self::Ledger();
        $definitions = [];
        foreach(self::Definition()['categories'] as $category_definition)
        {
            $definitions[$category_definition['seed_key']] = $category_definition;
        }
        if(empty($parent_key) || !isset($definitions[$parent_key]) || empty($ledger['entities'][$parent_key]['id']) || $ledger['entities'][$parent_key]['type'] !== 'category')
        {
            return '苗木目录台账缺少受管一级分类';
        }
        $parent_structure = [
            'type'            => 'category',
            'seed_key'        => $parent_key,
            'parent_seed_key' => null,
            'name'            => self::NormalizeName($definitions[$parent_key]['name']),
        ];
        $parent_hash = hash('sha256', json_encode($parent_structure, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));
        if(empty($ledger['entities'][$parent_key]['structure_sha256']) || !hash_equals((string) $ledger['entities'][$parent_key]['structure_sha256'], $parent_hash))
        {
            return '苗木目录台账一级分类结构哈希无效';
        }
        $expected_parent_id = intval($ledger['entities'][$parent_key]['id']);
        $category = Db::name('GoodsCategory')->where(['id'=>$category_id])->field('id,pid,name,is_enable')->find();
        if(empty($category) || intval($category['is_enable']) !== 1)
        {
            return '所选苗木分类不存在或已停用';
        }
        if(intval($category['pid']) !== $expected_parent_id || self::NormalizeName($category['name']) !== self::NormalizeName($definition['name']))
        {
            return '所选苗木分类结构已偏离目录台账';
        }
        $parent = Db::name('GoodsCategory')->where(['id'=>$expected_parent_id])->field('id,pid,name,is_enable')->find();
        if(empty($parent) || intval($parent['pid']) !== 0 || intval($parent['is_enable']) !== 1 || self::NormalizeName($parent['name']) !== self::NormalizeName($definitions[$parent_key]['name']))
        {
            return '所选苗木分类的一级分类不存在、已停用或层级无效';
        }
        if(Db::name('GoodsCategory')->where(['pid'=>intval($category_id), 'is_enable'=>1])->count() > 0)
        {
            return '商品主分类必须是无启用子分类的苗木叶子';
        }
        return null;
    }

    private static function NormalizeName($value)
    {
        $value = trim((string) $value);
        return function_exists('mb_strtolower') ? mb_strtolower($value, 'UTF-8') : strtolower($value);
    }

    private static function StrictSingleId($value)
    {
        if(!is_array($value))
        {
            $value = explode(',', (string) $value);
        }
        if(count($value) !== 1)
        {
            return null;
        }
        $item = reset($value);
        if(!is_scalar($item) || preg_match('/^[0-9]+$/D', trim((string) $item)) !== 1 || intval($item) <= 0)
        {
            return null;
        }
        return intval($item);
    }
}
?>
