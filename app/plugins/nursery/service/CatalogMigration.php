<?php
namespace app\plugins\nursery\service;

use think\facade\Db;
use app\service\SystemService;

class CatalogMigration
{
    private const MANIFEST_SCHEMA_VERSION = 1;
    private const CATALOG_VERSION = 1;
    private const MODES = ['existing', 'fresh'];
    private const EXECUTION_LOCK = 'shopxo_nursery_catalog_migration';

    public static function Preflight($mode = 'existing')
    {
        try {
            $mode = self::ValidateMode($mode);
            $definition = CatalogPolicy::Definition();
            self::ValidateDefinition($definition);
            $row = Db::name('Config')->where(['only_tag'=>CatalogPolicy::MANIFEST_TAG])->field('id,value')->find();
            if(empty($row))
            {
                self::AssertInitialRootNamesAvailable($definition, false);
            } else {
                self::VerifyLedger($definition, self::DecodeLedger($row['value']), false);
            }
            return DataReturn('苗木目录只读预检通过', 0, [
                'mode'            => $mode,
                'catalog_version' => intval($definition['catalog_version']),
                'write_performed' => false,
            ]);
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }
    }

    public static function Run($mode, $actor, $run_id)
    {
        $lock_connection = null;
        $transaction_started = false;
        try {
            $mode = self::ValidateMode($mode);
            self::ValidateExecutionMetadata($actor, $run_id);
            $definition = CatalogPolicy::Definition();
            self::ValidateDefinition($definition);
            $lock_connection = self::AcquireExecutionLock();
            $lock_connection->startTrans();
            $transaction_started = true;
            $row = Db::name('Config')->where(['only_tag'=>CatalogPolicy::MANIFEST_TAG])->lock(true)->field('id,value')->find();
            if(empty($row))
            {
                self::AssertInitialRootNamesAvailable($definition, true);
                $ledger = self::ImportDefinition($definition, $mode, $actor, $run_id);
                self::WriteLedger(null, $ledger);
                $created = count($ledger['entities']);
                $replayed = false;
            } else {
                $ledger = self::DecodeLedger($row['value']);
                self::VerifyLedger($definition, $ledger, true);
                $previous_run = self::FindRun($ledger, $run_id);
                if($previous_run !== null)
                {
                    if(!isset($previous_run['actor'], $previous_run['mode']) || (string) $previous_run['actor'] !== $actor || (string) $previous_run['mode'] !== $mode)
                    {
                        throw new \RuntimeException('该目录迁移 run-id 已绑定其他操作者或导入模式');
                    }
                    $lock_connection->commit();
                    $transaction_started = false;
                    return DataReturn('苗木目录迁移已执行过该 run-id', 0, [
                        'mode'            => $mode,
                        'catalog_version' => intval($definition['catalog_version']),
                        'created'         => 0,
                        'replayed'        => true,
                    ]);
                }
                $ledger['last_verified_at'] = time();
                self::AppendRun($ledger, $mode, $actor, $run_id, 0);
                self::WriteLedger(intval($row['id']), $ledger);
                $created = 0;
                $replayed = false;
            }
            $lock_connection->commit();
            $transaction_started = false;
            CatalogPolicy::ResetRuntimeCache();
            $cache_warning = null;
            try {
                MyCache(SystemService::CacheKey('shopxo.cache_goods_category_key'), null);
            } catch(\Throwable $cache_error) {
                $cache_warning = $cache_error->getMessage();
            }
            return DataReturn('苗木目录迁移完成', 0, [
                'mode'            => $mode,
                'catalog_version' => intval($definition['catalog_version']),
                'created'         => $created,
                'replayed'        => $replayed,
                'cache_warning'   => $cache_warning,
            ]);
        } catch(\Throwable $e) {
            if(!empty($transaction_started))
            {
                try {
                    $lock_connection->rollback();
                } catch(\Throwable $rollback_error) {
                }
            }
            return DataReturn($e->getMessage(), -1);
        } finally {
            if($lock_connection !== null)
            {
                self::ReleaseExecutionLock($lock_connection);
            }
        }
    }

    private static function ImportDefinition($definition, $mode, $actor, $run_id)
    {
        $entities = [];
        $remaining = $definition['categories'];
        while(!empty($remaining))
        {
            $progress = false;
            foreach($remaining as $index=>$category)
            {
                $parent_key = empty($category['parent_seed_key']) ? null : $category['parent_seed_key'];
                if($parent_key !== null && !isset($entities[$parent_key]))
                {
                    continue;
                }
                $parent_id = ($parent_key === null) ? 0 : intval($entities[$parent_key]['id']);
                self::AssertSiblingNameAvailable('GoodsCategory', 'pid', $parent_id, $category['name'], true);
                $data = [
                    'pid'                 => $parent_id,
                    'icon'                => '',
                    'icon_active'         => '',
                    'realistic_images'    => '',
                    'name'                => $category['name'],
                    'vice_name'           => isset($category['vice_name']) ? $category['vice_name'] : '',
                    'describe'            => isset($category['describe']) ? $category['describe'] : '',
                    'bg_color'            => '',
                    'big_images'          => '',
                    'is_home_recommended' => empty($category['is_home_recommended']) ? 0 : 1,
                    'sort'                => isset($category['sort']) ? intval($category['sort']) : 0,
                    'is_enable'           => empty($category['is_enable']) ? 0 : 1,
                    'seo_title'           => isset($category['seo_title']) ? $category['seo_title'] : '',
                    'seo_keywords'        => isset($category['seo_keywords']) ? $category['seo_keywords'] : '',
                    'seo_desc'            => isset($category['seo_desc']) ? $category['seo_desc'] : '',
                    'add_time'            => time(),
                    'upd_time'            => 0,
                ];
                $id = Db::name('GoodsCategory')->insertGetId($data);
                if($id <= 0)
                {
                    throw new \RuntimeException('苗木分类写入失败：'.$category['seed_key']);
                }
                $entities[$category['seed_key']] = [
                    'type'              => 'category',
                    'id'                => intval($id),
                    'parent_seed_key'   => $parent_key,
                    'created_version'   => intval($definition['catalog_version']),
                    'structure_sha256'  => self::CategoryStructureHash($category),
                ];
                unset($remaining[$index]);
                $progress = true;
            }
            if(!$progress)
            {
                throw new \RuntimeException('苗木分类清单存在循环或缺失父级');
            }
        }

        foreach($definition['spec_templates'] as $template)
        {
            $category_key = $template['category_seed_key'];
            if(!isset($entities[$category_key]))
            {
                throw new \RuntimeException('规格模板引用未知分类：'.$category_key);
            }
            $category_id = intval($entities[$category_key]['id']);
            self::AssertSiblingNameAvailable('GoodsSpecTemplate', 'category_id', $category_id, $template['name'], true);
            $id = Db::name('GoodsSpecTemplate')->insertGetId([
                'category_id' => $category_id,
                'name'        => $template['name'],
                'content'     => implode(',', $template['values']),
                'is_enable'   => empty($template['is_enable']) ? 0 : 1,
                'add_time'    => time(),
                'upd_time'    => 0,
            ]);
            if($id <= 0)
            {
                throw new \RuntimeException('苗木规格模板写入失败：'.$template['seed_key']);
            }
            $entities[$template['seed_key']] = [
                'type'              => 'spec_template',
                'id'                => intval($id),
                'category_seed_key' => $category_key,
                'created_version'   => intval($definition['catalog_version']),
                'structure_sha256'  => self::SpecStructureHash($template),
            ];
        }

        foreach($definition['parameter_templates'] as $template)
        {
            $category_key = $template['category_seed_key'];
            if(!isset($entities[$category_key]))
            {
                throw new \RuntimeException('参数模板引用未知分类：'.$category_key);
            }
            $category_id = intval($entities[$category_key]['id']);
            self::AssertSiblingNameAvailable('GoodsParamsTemplate', 'category_id', $category_id, $template['name'], true);
            $id = Db::name('GoodsParamsTemplate')->insertGetId([
                'category_id'  => $category_id,
                'name'         => $template['name'],
                'is_enable'    => empty($template['is_enable']) ? 0 : 1,
                'config_count' => count($definition['parameter_fields']),
                'add_time'     => time(),
                'upd_time'     => 0,
            ]);
            if($id <= 0)
            {
                throw new \RuntimeException('苗木参数模板写入失败：'.$template['seed_key']);
            }
            $config_ids = [];
            foreach($definition['parameter_fields'] as $field)
            {
                $config_id = Db::name('GoodsParamsTemplateConfig')->insertGetId([
                    'template_id' => intval($id),
                    'scope'       => intval($field['scope']),
                    'name'        => $field['name'],
                    'required'    => empty($field['required']) ? 0 : 1,
                    'data_type'   => intval($field['data_type']),
                    'value'       => isset($field['value']) ? $field['value'] : '',
                    'add_time'    => time(),
                ]);
                if($config_id <= 0)
                {
                    throw new \RuntimeException('苗木参数字段写入失败：'.$field['key']);
                }
                $config_ids[$field['key']] = intval($config_id);
            }
            $entities[$template['seed_key']] = [
                'type'              => 'parameter_template',
                'id'                => intval($id),
                'category_seed_key' => $category_key,
                'config_ids'        => $config_ids,
                'created_version'   => intval($definition['catalog_version']),
                'structure_sha256'  => self::ParameterStructureHash($template, $definition['parameter_fields']),
            ];
        }

        $ledger = [
            'manifest_schema_version' => self::MANIFEST_SCHEMA_VERSION,
            'catalog_version'         => intval($definition['catalog_version']),
            'payload_sha256'          => self::PayloadHash($definition),
            'entities'                => $entities,
            'created_at'              => time(),
            'last_verified_at'        => time(),
            'runs'                    => [],
        ];
        self::AppendRun($ledger, $mode, $actor, $run_id, count($entities));
        return $ledger;
    }

    private static function VerifyLedger($definition, $ledger, $lock_siblings = false)
    {
        if(intval($ledger['manifest_schema_version']) !== self::MANIFEST_SCHEMA_VERSION || intval($ledger['catalog_version']) !== intval($definition['catalog_version']))
        {
            throw new \RuntimeException('苗木目录台账版本与当前清单不兼容');
        }
        if(!hash_equals((string) $ledger['payload_sha256'], self::PayloadHash($definition)))
        {
            throw new \RuntimeException('苗木目录清单内容已变化但 catalog_version 未升级');
        }
        if(empty($ledger['entities']) || !is_array($ledger['entities']))
        {
            throw new \RuntimeException('苗木目录台账实体为空');
        }

        foreach($definition['categories'] as $category)
        {
            $entity = self::RequiredEntity($ledger, $category['seed_key'], 'category');
            $row = Db::name('GoodsCategory')->where(['id'=>intval($entity['id'])])->field('id,pid,name')->find();
            if(empty($row))
            {
                throw new \RuntimeException('受管苗木分类 ID 已缺失：'.$category['seed_key']);
            }
            $parent_key = empty($category['parent_seed_key']) ? null : $category['parent_seed_key'];
            $expected_parent_id = ($parent_key === null) ? 0 : intval(self::RequiredEntity($ledger, $parent_key, 'category')['id']);
            if(intval($row['pid']) !== $expected_parent_id || self::NormalizeName($row['name']) !== self::NormalizeName($category['name']) || !hash_equals((string) $entity['structure_sha256'], self::CategoryStructureHash($category)))
            {
                throw new \RuntimeException('受管苗木分类结构已漂移：'.$category['seed_key']);
            }
            self::AssertManagedSiblingUnique('GoodsCategory', 'pid', $expected_parent_id, $category['name'], intval($entity['id']), $lock_siblings);
        }

        foreach($definition['spec_templates'] as $template)
        {
            $entity = self::RequiredEntity($ledger, $template['seed_key'], 'spec_template');
            $category = self::RequiredEntity($ledger, $template['category_seed_key'], 'category');
            $row = Db::name('GoodsSpecTemplate')->where(['id'=>intval($entity['id'])])->field('id,category_id,name')->find();
            if(empty($row) || intval($row['category_id']) !== intval($category['id']) || self::NormalizeName($row['name']) !== self::NormalizeName($template['name']) || !hash_equals((string) $entity['structure_sha256'], self::SpecStructureHash($template)))
            {
                throw new \RuntimeException('受管苗木规格模板结构已漂移：'.$template['seed_key']);
            }
            self::AssertManagedSiblingUnique('GoodsSpecTemplate', 'category_id', intval($category['id']), $template['name'], intval($entity['id']), $lock_siblings);
        }

        foreach($definition['parameter_templates'] as $template)
        {
            $entity = self::RequiredEntity($ledger, $template['seed_key'], 'parameter_template');
            $category = self::RequiredEntity($ledger, $template['category_seed_key'], 'category');
            $row = Db::name('GoodsParamsTemplate')->where(['id'=>intval($entity['id'])])->field('id,category_id,name,config_count')->find();
            if(empty($row) || intval($row['category_id']) !== intval($category['id']) || self::NormalizeName($row['name']) !== self::NormalizeName($template['name']) || intval($row['config_count']) !== count($definition['parameter_fields']) || !hash_equals((string) $entity['structure_sha256'], self::ParameterStructureHash($template, $definition['parameter_fields'])))
            {
                throw new \RuntimeException('受管苗木参数模板结构已漂移：'.$template['seed_key']);
            }
            self::AssertManagedSiblingUnique('GoodsParamsTemplate', 'category_id', intval($category['id']), $template['name'], intval($entity['id']), $lock_siblings);
            if(empty($entity['config_ids']) || !is_array($entity['config_ids']) || count($entity['config_ids']) !== count($definition['parameter_fields']) || count(array_unique(array_map('intval', array_values($entity['config_ids'])))) !== count($definition['parameter_fields']))
            {
                throw new \RuntimeException('苗木参数模板台账缺少字段 ID：'.$template['seed_key']);
            }
            $configs = Db::name('GoodsParamsTemplateConfig')->where(['template_id'=>intval($entity['id'])])->field('id,template_id,name,scope,required,data_type')->select()->toArray();
            if(count($configs) !== count($definition['parameter_fields']))
            {
                throw new \RuntimeException('受管苗木参数字段集合已漂移：'.$template['seed_key']);
            }
            $config_map = [];
            foreach($configs as $config)
            {
                $config_map[intval($config['id'])] = $config;
            }
            foreach($definition['parameter_fields'] as $field)
            {
                if(empty($entity['config_ids'][$field['key']]))
                {
                    throw new \RuntimeException('苗木参数字段台账缺失：'.$field['key']);
                }
                $config_id = intval($entity['config_ids'][$field['key']]);
                $config = isset($config_map[$config_id]) ? $config_map[$config_id] : null;
                if(empty($config) || intval($config['template_id']) !== intval($entity['id']) || self::NormalizeName($config['name']) !== self::NormalizeName($field['name']) || intval($config['scope']) !== intval($field['scope']) || intval($config['required']) !== (empty($field['required']) ? 0 : 1) || intval($config['data_type']) !== intval($field['data_type']))
                {
                    throw new \RuntimeException('受管苗木参数字段结构已漂移：'.$template['seed_key'].'/'.$field['key']);
                }
            }
        }
        return true;
    }

    private static function ValidateDefinition($definition)
    {
        if(intval($definition['schema_version']) !== self::MANIFEST_SCHEMA_VERSION || intval($definition['catalog_version']) !== self::CATALOG_VERSION)
        {
            throw new \RuntimeException('苗木目录清单版本不受支持');
        }
        foreach(['categories', 'spec_templates', 'parameter_templates', 'parameter_fields'] as $key)
        {
            if(empty($definition[$key]) || !is_array($definition[$key]))
            {
                throw new \RuntimeException('苗木目录清单缺少：'.$key);
            }
        }
        if(empty($definition['settings']) || !is_array($definition['settings']))
        {
            throw new \RuntimeException('苗木目录清单缺少 settings');
        }
        $max_depth = intval(isset($definition['settings']['max_category_depth']) ? $definition['settings']['max_category_depth'] : 0);
        $max_dimensions = intval(isset($definition['settings']['max_spec_dimensions']) ? $definition['settings']['max_spec_dimensions'] : 0);
        if($max_depth < 1 || $max_depth > 3 || $max_dimensions < 1 || $max_dimensions > 2 || empty($definition['settings']['inventory_units']) || !is_array($definition['settings']['inventory_units']))
        {
            throw new \RuntimeException('苗木目录 settings 超出已批准边界');
        }
        $keys = [];
        $categories = [];
        foreach($definition['categories'] as $category)
        {
            self::RequireSeed($category, ['seed_key', 'name']);
            if(isset($keys[$category['seed_key']]))
            {
                throw new \RuntimeException('苗木目录 seed_key 重复：'.$category['seed_key']);
            }
            $keys[$category['seed_key']] = true;
            $categories[$category['seed_key']] = $category;
        }
        foreach($categories as $category)
        {
            if(!empty($category['parent_seed_key']) && !isset($categories[$category['parent_seed_key']]))
            {
                throw new \RuntimeException('苗木分类父 seed_key 不存在：'.$category['seed_key']);
            }
            $depth = 1;
            $parent_key = empty($category['parent_seed_key']) ? null : $category['parent_seed_key'];
            $visited = [$category['seed_key']=>true];
            while($parent_key !== null)
            {
                if(isset($visited[$parent_key]) || !isset($categories[$parent_key]))
                {
                    throw new \RuntimeException('苗木分类层级存在循环：'.$category['seed_key']);
                }
                $visited[$parent_key] = true;
                $depth++;
                $parent_key = empty($categories[$parent_key]['parent_seed_key']) ? null : $categories[$parent_key]['parent_seed_key'];
            }
            if($depth > $max_depth)
            {
                throw new \RuntimeException('苗木分类层级超过清单上限：'.$category['seed_key']);
            }
        }
        $spec_counts = [];
        $template_names = [];
        foreach($definition['spec_templates'] as $template)
        {
            self::RequireSeed($template, ['seed_key', 'category_seed_key', 'name']);
            if(isset($keys[$template['seed_key']]) || !isset($categories[$template['category_seed_key']]))
            {
                throw new \RuntimeException('苗木模板 seed_key 重复或分类引用无效：'.$template['seed_key']);
            }
            $keys[$template['seed_key']] = true;
            $category_key = $template['category_seed_key'];
            $spec_counts[$category_key] = isset($spec_counts[$category_key]) ? $spec_counts[$category_key]+1 : 1;
            $name_key = $category_key.'|'.self::NormalizeName($template['name']);
            if(isset($template_names[$name_key]) || empty($template['values']) || !is_array($template['values']))
            {
                throw new \RuntimeException('苗木规格模板名称重复或值为空：'.$template['seed_key']);
            }
            $template_names[$name_key] = true;
            if($spec_counts[$category_key] > $max_dimensions)
            {
                throw new \RuntimeException('苗木规格模板超过两维：'.$category_key);
            }
            if(substr($template['name'], -4) === '(cm)')
            {
                foreach($template['values'] as $value)
                {
                    if(!is_string($value) || preg_match('/^[0-9]+(?:\.[0-9]+)?(?:-[0-9]+(?:\.[0-9]+)?)?$/D', $value) !== 1)
                    {
                        throw new \RuntimeException('苗木厘米规格值无效：'.$template['seed_key']);
                    }
                    $range = explode('-', $value);
                    $minimum = floatval($range[0]);
                    $maximum = isset($range[1]) ? floatval($range[1]) : $minimum;
                    if($minimum <= 0 || $maximum < $minimum)
                    {
                        throw new \RuntimeException('苗木厘米规格值必须为正数单值或闭区间：'.$template['seed_key']);
                    }
                }
            }
        }
        foreach($definition['parameter_templates'] as $template)
        {
            self::RequireSeed($template, ['seed_key', 'category_seed_key', 'name']);
            if(isset($keys[$template['seed_key']]) || !isset($categories[$template['category_seed_key']]))
            {
                throw new \RuntimeException('苗木参数模板 seed_key 重复或分类引用无效：'.$template['seed_key']);
            }
            $keys[$template['seed_key']] = true;
            $name_key = $template['category_seed_key'].'|'.self::NormalizeName($template['name']);
            if(isset($template_names[$name_key]))
            {
                throw new \RuntimeException('苗木模板同分类名称重复：'.$template['seed_key']);
            }
            $template_names[$name_key] = true;
        }
        $field_keys = [];
        foreach($definition['parameter_fields'] as $field)
        {
            self::RequireSeed($field, ['key', 'name', 'scope', 'data_type']);
            if(isset($field_keys[$field['key']]))
            {
                throw new \RuntimeException('苗木参数 key 重复：'.$field['key']);
            }
            $field_keys[$field['key']] = true;
            if(!in_array(intval($field['scope']), [0, 1, 2], true) || !in_array(intval($field['data_type']), [0, 1, 2], true))
            {
                throw new \RuntimeException('苗木参数字段 scope 或 data_type 无效：'.$field['key']);
            }
        }
    }

    private static function AssertInitialRootNamesAvailable($definition, $lock_siblings)
    {
        foreach($definition['categories'] as $category)
        {
            if(empty($category['parent_seed_key']))
            {
                self::AssertSiblingNameAvailable('GoodsCategory', 'pid', 0, $category['name'], $lock_siblings);
            }
        }
    }

    private static function AssertSiblingNameAvailable($table, $parent_field, $parent_id, $name, $lock_siblings)
    {
        $query = Db::name($table)->where([$parent_field=>intval($parent_id)]);
        if($lock_siblings)
        {
            $query = $query->lock(true);
        }
        $rows = $query->column('name');
        $expected = self::NormalizeName($name);
        foreach($rows as $existing)
        {
            if(self::NormalizeName($existing) === $expected)
            {
                throw new \RuntimeException('存在同父同名未托管数据：'.$name);
            }
        }
    }

    private static function AssertManagedSiblingUnique($table, $parent_field, $parent_id, $name, $managed_id, $lock_siblings)
    {
        $query = Db::name($table)->where([$parent_field=>intval($parent_id)]);
        if($lock_siblings)
        {
            $query = $query->lock(true);
        }
        $rows = $query->field('id,name')->select()->toArray();
        $expected = self::NormalizeName($name);
        foreach($rows as $row)
        {
            if(intval($row['id']) !== intval($managed_id) && self::NormalizeName($row['name']) === $expected)
            {
                throw new \RuntimeException('存在同父同名未托管数据：'.$name);
            }
        }
    }

    private static function WriteLedger($id, $ledger)
    {
        $value = json_encode($ledger, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
        if($value === false)
        {
            throw new \RuntimeException('苗木目录台账编码失败');
        }
        if(empty($id))
        {
            $id = Db::name('Config')->insertGetId([
                'value'      => $value,
                'name'       => '苗木目录迁移台账',
                'describe'   => 'nursery 插件目录、规格与参数模板的非敏感所有权台账',
                'error_tips' => '',
                'type'       => 'common',
                'only_tag'   => CatalogPolicy::MANIFEST_TAG,
                'upd_time'   => time(),
            ]);
            if($id <= 0)
            {
                throw new \RuntimeException('苗木目录台账写入失败');
            }
        } elseif(Db::name('Config')->where(['id'=>intval($id), 'only_tag'=>CatalogPolicy::MANIFEST_TAG])->update(['value'=>$value, 'upd_time'=>time()]) === false) {
            throw new \RuntimeException('苗木目录台账更新失败');
        }
    }

    private static function DecodeLedger($value)
    {
        $ledger = empty($value) ? null : json_decode($value, true);
        if(!is_array($ledger))
        {
            throw new \RuntimeException('苗木目录台账 JSON 无效');
        }
        return $ledger;
    }

    private static function RequiredEntity($ledger, $seed_key, $type)
    {
        if(!isset($ledger['entities'][$seed_key]) || !is_array($ledger['entities'][$seed_key]) || $ledger['entities'][$seed_key]['type'] !== $type || empty($ledger['entities'][$seed_key]['id']))
        {
            throw new \RuntimeException('苗木目录台账实体缺失或类型无效：'.$seed_key);
        }
        return $ledger['entities'][$seed_key];
    }

    private static function AppendRun(&$ledger, $mode, $actor, $run_id, $created)
    {
        if(!isset($ledger['runs']) || !is_array($ledger['runs']))
        {
            $ledger['runs'] = [];
        }
        $ledger['runs'][] = [
            'run_id'     => $run_id,
            'actor'      => $actor,
            'mode'       => $mode,
            'created'    => intval($created),
            'applied_at' => time(),
        ];
    }

    private static function FindRun($ledger, $run_id)
    {
        if(empty($ledger['runs']) || !is_array($ledger['runs']))
        {
            return null;
        }
        foreach(array_reverse($ledger['runs']) as $run)
        {
            if(is_array($run) && isset($run['run_id']) && $run['run_id'] === $run_id)
            {
                return $run;
            }
        }
        return null;
    }

    private static function CategoryStructureHash($category)
    {
        return self::StructureHash([
            'type'            => 'category',
            'seed_key'        => $category['seed_key'],
            'parent_seed_key' => empty($category['parent_seed_key']) ? null : $category['parent_seed_key'],
            'name'            => self::NormalizeName($category['name']),
        ]);
    }

    private static function SpecStructureHash($template)
    {
        return self::StructureHash([
            'type'              => 'spec_template',
            'seed_key'          => $template['seed_key'],
            'category_seed_key' => $template['category_seed_key'],
            'name'              => self::NormalizeName($template['name']),
        ]);
    }

    private static function ParameterStructureHash($template, $fields)
    {
        $field_structure = [];
        foreach($fields as $field)
        {
            $field_structure[] = [
                'key'       => $field['key'],
                'name'      => self::NormalizeName($field['name']),
                'scope'     => intval($field['scope']),
                'required'  => empty($field['required']) ? 0 : 1,
                'data_type' => intval($field['data_type']),
            ];
        }
        return self::StructureHash([
            'type'              => 'parameter_template',
            'seed_key'          => $template['seed_key'],
            'category_seed_key' => $template['category_seed_key'],
            'name'              => self::NormalizeName($template['name']),
            'fields'            => $field_structure,
        ]);
    }

    private static function StructureHash($value)
    {
        return hash('sha256', json_encode($value, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));
    }

    private static function PayloadHash($definition)
    {
        return self::StructureHash($definition);
    }

    private static function NormalizeName($value)
    {
        $value = trim((string) $value);
        return function_exists('mb_strtolower') ? mb_strtolower($value, 'UTF-8') : strtolower($value);
    }

    private static function ValidateMode($mode)
    {
        if(!is_string($mode) || !in_array($mode, self::MODES, true))
        {
            throw new \InvalidArgumentException('目录迁移 mode 必须是 existing 或 fresh');
        }
        return $mode;
    }

    private static function ValidateExecutionMetadata($actor, $run_id)
    {
        if(!is_string($actor) || preg_match('/^[A-Za-z0-9._:@\/-]{2,80}$/D', $actor) !== 1)
        {
            throw new \InvalidArgumentException('目录迁移 actor 格式无效');
        }
        if(!is_string($run_id) || preg_match('/^[A-Za-z0-9][A-Za-z0-9._:-]{5,100}$/D', $run_id) !== 1)
        {
            throw new \InvalidArgumentException('目录迁移 run-id 格式无效');
        }
    }

    private static function AcquireExecutionLock()
    {
        $connection = Db::connect();
        $rows = $connection->query("SELECT GET_LOCK('".self::EXECUTION_LOCK."', 30) AS acquired", [], true);
        if(empty($rows) || !isset($rows[0]['acquired']) || intval($rows[0]['acquired']) !== 1)
        {
            throw new \RuntimeException('无法获取苗木目录迁移串行锁');
        }
        return $connection;
    }

    private static function ReleaseExecutionLock($connection)
    {
        $rows = $connection->query("SELECT RELEASE_LOCK('".self::EXECUTION_LOCK."') AS released", [], true);
        if(empty($rows) || !isset($rows[0]['released']) || intval($rows[0]['released']) !== 1)
        {
            throw new \RuntimeException('苗木目录迁移已结束，但串行锁释放失败');
        }
    }

    private static function RequireSeed($item, $fields)
    {
        if(!is_array($item))
        {
            throw new \RuntimeException('苗木目录清单项必须是 object');
        }
        foreach($fields as $field)
        {
            if(!array_key_exists($field, $item) || $item[$field] === '')
            {
                throw new \RuntimeException('苗木目录清单项缺少字段：'.$field);
            }
        }
    }
}
?>
