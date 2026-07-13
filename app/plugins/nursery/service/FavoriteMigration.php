<?php
namespace app\plugins\nursery\service;

use think\facade\Db;

class FavoriteMigration
{
    private const MANIFEST_SCHEMA_VERSION = 1;
    private const FAVORITE_SCHEMA_VERSION = 1;
    private const EXECUTION_LOCK = 'shopxo_nursery_favorite_schema_v1';

    public static function Status()
    {
        try {
            $definition = self::Definition();
            $inspection = self::Inspect($definition, true);
            $ledger = self::ReadLedger($definition, false);
            return DataReturn('苗木收藏结构状态读取成功', 0, [
                'schema_version'    => self::FAVORITE_SCHEMA_VERSION,
                'ready'             => $inspection['ready'] && $ledger !== null,
                'migration_required'=> !$inspection['ready'] || $ledger === null,
                'duplicate_groups'  => $inspection['duplicate_groups'],
                'duplicate_rows'    => $inspection['duplicate_rows'],
                'index_name'        => $inspection['index_name'],
                'ledger_present'    => $ledger !== null,
                'write_performed'   => false,
            ]);
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }
    }

    public static function Preflight()
    {
        try {
            $definition = self::Definition();
            $inspection = self::Inspect($definition, true);
            $ledger = self::ReadLedger($definition, false);
            $ready = $inspection['ready'] && $ledger !== null;
            return DataReturn('苗木收藏结构只读预检通过', 0, [
                'schema_version'    => self::FAVORITE_SCHEMA_VERSION,
                'ready'             => $ready,
                'migration_required'=> !$ready,
                'duplicate_groups'  => 0,
                'duplicate_rows'    => 0,
                'index_name'        => $inspection['index_name'],
                'ledger_present'    => $ledger !== null,
                'write_performed'   => false,
            ]);
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }
    }

    public static function Run($actor, $run_id)
    {
        $connection = null;
        try {
            self::ValidateExecutionMetadata($actor, $run_id);
            $definition = self::Definition();
            $connection = self::AcquireExecutionLock();
            $inspection = self::Inspect($definition, true);
            $ledger_row = self::ReadLedger($definition, true);
            $previous_run = empty($ledger_row) ? null : self::FindRun($ledger_row['ledger'], $run_id);
            if($previous_run !== null)
            {
                if(!isset($previous_run['actor']) || (string) $previous_run['actor'] !== $actor)
                {
                    throw new \RuntimeException('该收藏迁移 run-id 已绑定其他操作者');
                }
                self::AssertReady();
                return DataReturn('苗木收藏迁移已执行过该 run-id', 0, [
                    'schema_version' => self::FAVORITE_SCHEMA_VERSION,
                    'index_created'  => false,
                    'replayed'       => true,
                ]);
            }

            $index_created = false;
            if(!$inspection['ready'])
            {
                self::CreateUniqueIndex($definition);
                $index_created = true;
            }
            $inspection = self::Inspect($definition, true);
            if(!$inspection['ready'])
            {
                throw new \RuntimeException('苗木收藏唯一索引创建后校验失败');
            }

            $ledger = empty($ledger_row) ? self::NewLedger($definition) : $ledger_row['ledger'];
            self::AppendRun($ledger, $actor, $run_id, $index_created);
            self::WriteLedger(empty($ledger_row) ? null : intval($ledger_row['id']), $definition, $ledger);
            self::AssertReady();
            return DataReturn('苗木收藏迁移完成', 0, [
                'schema_version' => self::FAVORITE_SCHEMA_VERSION,
                'index_created'  => $index_created,
                'replayed'       => false,
            ]);
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        } finally {
            if($connection !== null)
            {
                self::ReleaseExecutionLock($connection);
            }
        }
    }

    public static function AssertReady()
    {
        $definition = self::Definition();
        $inspection = self::Inspect($definition, false);
        if(!$inspection['ready'])
        {
            throw new \RuntimeException('苗木收藏写入未启用：请先完成 favorite schema v1 迁移');
        }
        if(self::ReadLedger($definition, false) === null)
        {
            throw new \RuntimeException('苗木收藏写入未启用：迁移台账缺失');
        }
        return true;
    }

    private static function Definition()
    {
        $file = dirname(__DIR__).DIRECTORY_SEPARATOR.'favorite-schema-v1.json';
        if(!is_file($file))
        {
            throw new \RuntimeException('苗木收藏结构清单不存在');
        }
        $raw = file_get_contents($file);
        $definition = ($raw === false) ? null : json_decode($raw, true);
        if(!is_array($definition) || intval($definition['schema_version'] ?? 0) !== self::MANIFEST_SCHEMA_VERSION || intval($definition['favorite_schema_version'] ?? 0) !== self::FAVORITE_SCHEMA_VERSION)
        {
            throw new \RuntimeException('苗木收藏结构清单版本无效');
        }
        if(($definition['table'] ?? '') !== 'goods_favor' || ($definition['unique_index']['name'] ?? '') !== 'uniq_nursery_user_goods' || ($definition['unique_index']['columns'] ?? null) !== ['user_id', 'goods_id'])
        {
            throw new \RuntimeException('苗木收藏结构清单内容无效');
        }
        if(($definition['ledger']['only_tag'] ?? '') !== 'plugins_nursery_favorite_schema_v1')
        {
            throw new \RuntimeException('苗木收藏迁移台账标识无效');
        }
        $definition['payload_sha256'] = hash('sha256', $raw);
        return $definition;
    }

    private static function Inspect($definition, $check_duplicates)
    {
        $table = self::TableName();
        $duplicates = $check_duplicates ? self::DuplicateSummary($table) : ['duplicate_groups'=>0, 'duplicate_rows'=>0];
        if($check_duplicates && $duplicates['duplicate_groups'] > 0)
        {
            throw new \RuntimeException('检测到历史重复收藏，迁移已停止；冲突组数：'.$duplicates['duplicate_groups'].'，冗余行数：'.$duplicates['duplicate_rows']);
        }

        $indexes = self::Indexes($table);
        $required_name = $definition['unique_index']['name'];
        $required_columns = $definition['unique_index']['columns'];
        if(isset($indexes[$required_name]) && (!$indexes[$required_name]['unique'] || $indexes[$required_name]['columns'] !== $required_columns))
        {
            throw new \RuntimeException('苗木收藏唯一索引同名但结构不一致');
        }

        $compatible_name = '';
        foreach($indexes as $name=>$index)
        {
            if($index['unique'] && $index['columns'] === $required_columns)
            {
                $compatible_name = $name;
                break;
            }
        }
        return [
            'ready'            => $compatible_name !== '',
            'index_name'       => $compatible_name,
            'duplicate_groups' => 0,
            'duplicate_rows'   => 0,
        ];
    }

    private static function TableName()
    {
        $table = Db::name('GoodsFavor')->getTable();
        if(!is_string($table) || preg_match('/^[A-Za-z0-9_]+$/D', $table) !== 1)
        {
            throw new \RuntimeException('苗木收藏数据表名称无效');
        }
        return $table;
    }

    private static function DuplicateSummary($table)
    {
        $sql = 'SELECT COUNT(*) AS duplicate_groups, COALESCE(SUM(group_count-1), 0) AS duplicate_rows FROM (SELECT COUNT(*) AS group_count FROM `'.$table.'` GROUP BY `user_id`, `goods_id` HAVING COUNT(*) > 1) AS duplicate_favorites';
        $rows = Db::query($sql);
        $row = empty($rows) ? [] : $rows[0];
        return [
            'duplicate_groups' => intval($row['duplicate_groups'] ?? 0),
            'duplicate_rows'   => intval($row['duplicate_rows'] ?? 0),
        ];
    }

    private static function Indexes($table)
    {
        $result = [];
        foreach(Db::query('SHOW INDEX FROM `'.$table.'`') as $row)
        {
            $name = (string) self::RowValue($row, 'Key_name');
            $column = (string) self::RowValue($row, 'Column_name');
            $sequence = intval(self::RowValue($row, 'Seq_in_index'));
            if($name === '' || $column === '' || $sequence <= 0)
            {
                throw new \RuntimeException('苗木收藏索引元数据无效');
            }
            if(!isset($result[$name]))
            {
                $result[$name] = [
                    'unique'  => intval(self::RowValue($row, 'Non_unique')) === 0,
                    'columns' => [],
                ];
            }
            $result[$name]['columns'][$sequence] = $column;
        }
        foreach($result as &$index)
        {
            ksort($index['columns']);
            $index['columns'] = array_values($index['columns']);
        }
        unset($index);
        return $result;
    }

    private static function RowValue($row, $name)
    {
        foreach($row as $key=>$value)
        {
            if(strcasecmp((string) $key, $name) === 0)
            {
                return $value;
            }
        }
        return null;
    }

    private static function CreateUniqueIndex($definition)
    {
        $table = self::TableName();
        $name = $definition['unique_index']['name'];
        Db::execute('ALTER TABLE `'.$table.'` ADD UNIQUE INDEX `'.$name.'` (`user_id`, `goods_id`)');
    }

    private static function ReadLedger($definition, $lock)
    {
        $query = Db::name('Config')->where(['only_tag'=>$definition['ledger']['only_tag']])->field('id,value');
        if($lock)
        {
            $query = $query->lock(true);
        }
        $row = $query->find();
        if(empty($row))
        {
            return null;
        }
        $ledger = json_decode((string) $row['value'], true);
        if(!is_array($ledger) || intval($ledger['schema_version'] ?? 0) !== self::FAVORITE_SCHEMA_VERSION || !isset($ledger['payload_sha256']) || !hash_equals($definition['payload_sha256'], (string) $ledger['payload_sha256']))
        {
            throw new \RuntimeException('苗木收藏迁移台账无效或与清单不一致');
        }
        return ['id'=>intval($row['id']), 'ledger'=>$ledger];
    }

    private static function NewLedger($definition)
    {
        return [
            'schema_version' => self::FAVORITE_SCHEMA_VERSION,
            'payload_sha256'=> $definition['payload_sha256'],
            'index_name'    => $definition['unique_index']['name'],
            'columns'       => $definition['unique_index']['columns'],
            'runs'          => [],
        ];
    }

    private static function WriteLedger($id, $definition, $ledger)
    {
        $value = json_encode($ledger, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
        if($value === false)
        {
            throw new \RuntimeException('苗木收藏迁移台账编码失败');
        }
        $data = [
            'value'      => $value,
            'name'       => $definition['ledger']['name'],
            'describe'   => 'nursery 插件收藏唯一索引的非敏感迁移台账',
            'error_tips' => '',
            'type'       => 'common',
            'only_tag'   => $definition['ledger']['only_tag'],
            'upd_time'   => time(),
        ];
        if(empty($id))
        {
            if(Db::name('Config')->insertGetId($data) <= 0)
            {
                throw new \RuntimeException('苗木收藏迁移台账写入失败');
            }
        } elseif(Db::name('Config')->where(['id'=>intval($id), 'only_tag'=>$definition['ledger']['only_tag']])->update($data) === false) {
            throw new \RuntimeException('苗木收藏迁移台账更新失败');
        }
    }

    private static function AppendRun(&$ledger, $actor, $run_id, $index_created)
    {
        if(!isset($ledger['runs']) || !is_array($ledger['runs']))
        {
            $ledger['runs'] = [];
        }
        $ledger['runs'][] = [
            'run_id'        => $run_id,
            'actor'         => $actor,
            'index_created' => $index_created,
            'applied_at'    => time(),
        ];
        $ledger['last_verified_at'] = time();
    }

    private static function FindRun($ledger, $run_id)
    {
        foreach(array_reverse($ledger['runs'] ?? []) as $run)
        {
            if(is_array($run) && ($run['run_id'] ?? '') === $run_id)
            {
                return $run;
            }
        }
        return null;
    }

    private static function ValidateExecutionMetadata($actor, $run_id)
    {
        if(!is_string($actor) || preg_match('/^[A-Za-z0-9._:@\/-]{2,80}$/D', $actor) !== 1)
        {
            throw new \InvalidArgumentException('收藏迁移 actor 格式无效');
        }
        if(!is_string($run_id) || preg_match('/^[A-Za-z0-9][A-Za-z0-9._:-]{5,100}$/D', $run_id) !== 1)
        {
            throw new \InvalidArgumentException('收藏迁移 run-id 格式无效');
        }
    }

    private static function AcquireExecutionLock()
    {
        $connection = Db::connect();
        $rows = $connection->query("SELECT GET_LOCK('".self::EXECUTION_LOCK."', 30) AS acquired", [], true);
        if(empty($rows) || intval($rows[0]['acquired'] ?? 0) !== 1)
        {
            throw new \RuntimeException('无法获取苗木收藏迁移串行锁');
        }
        return $connection;
    }

    private static function ReleaseExecutionLock($connection)
    {
        try {
            $rows = $connection->query("SELECT RELEASE_LOCK('".self::EXECUTION_LOCK."') AS released", [], true);
            if(empty($rows) || intval($rows[0]['released'] ?? 0) !== 1)
            {
                throw new \RuntimeException('苗木收藏迁移锁释放失败');
            }
        } catch(\Throwable $e) {
            throw $e;
        }
    }
}
?>
