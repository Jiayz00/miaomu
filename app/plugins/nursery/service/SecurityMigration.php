<?php
namespace app\plugins\nursery\service;

use think\facade\Db;

/**
 * Forward-only schema management for the nursery security tables.
 *
 * The manifest is the contract for both new and existing installations.  A
 * same-name table with a different shape is an operator error; the migration
 * never tries to make that table look right by removing data or metadata.
 */
class SecurityMigration
{
    private const MANIFEST_SCHEMA_VERSION = 1;
    private const SECURITY_SCHEMA_VERSION = 1;
    private const EXECUTION_LOCK = 'shopxo_nursery_security_schema_v1';
    private const TABLE_KEYS = ['favorite_rate_limit', 'goods_audit'];

    public static function Status()
    {
        try {
            $definition = self::Definition();
            $inspection = self::Inspect($definition);
            $ledger = self::ReadLedger($definition, null, false);
            $ready = $inspection['ready'] && $ledger !== null;
            return DataReturn('苗木安全结构状态读取成功', 0, [
                'schema_version'     => self::SECURITY_SCHEMA_VERSION,
                'ready'              => $ready,
                'migration_required' => !$ready,
                'tables'             => $inspection['tables'],
                'ledger_present'     => $ledger !== null,
                'write_performed'    => false,
            ]);
        } catch(\Throwable $e) {
            return DataReturn($e->getMessage(), -1);
        }
    }

    public static function Preflight()
    {
        try {
            $definition = self::Definition();
            $inspection = self::Inspect($definition);
            $ledger = self::ReadLedger($definition, null, false);
            $ready = $inspection['ready'] && $ledger !== null;
            return DataReturn('苗木安全结构只读预检通过', 0, [
                'schema_version'     => self::SECURITY_SCHEMA_VERSION,
                'ready'              => $ready,
                'migration_required' => !$ready,
                'tables'             => $inspection['tables'],
                'ledger_present'     => $ledger !== null,
                'write_performed'    => false,
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

            $inspection = self::Inspect($definition, $connection);
            $ledger_row = self::ReadLedger($definition, $connection, true);
            $previous_run = empty($ledger_row) ? null : self::FindRun($ledger_row['ledger'], $run_id);
            if($previous_run !== null)
            {
                if((string) ($previous_run['actor'] ?? '') !== $actor)
                {
                    throw new \RuntimeException('该安全迁移 run-id 已绑定其他操作者');
                }
                self::AssertReady($connection);
                return DataReturn('苗木安全迁移已执行过该 run-id', 0, [
                    'schema_version' => self::SECURITY_SCHEMA_VERSION,
                    'created'        => [],
                    'repaired'       => [],
                    'replayed'       => true,
                ]);
            }

            $created = [];
            $repaired = [];
            foreach(self::TABLE_KEYS as $key)
            {
                $table_state = $inspection['tables'][$key];
                if(empty($table_state['exists']))
                {
                    self::CreateTable($definition, $key, $connection);
                    $created[] = $key;
                    // DDL is followed by a real metadata inspection.  A
                    // partial create therefore remains visible for the next
                    // forward repair instead of being silently accepted.
                    $inspection = self::Inspect($definition, $connection);
                    continue;
                }

                if(empty($table_state['columns']))
                {
                    throw new \RuntimeException('苗木安全表字段结构尚未完整，禁止先补索引：'.$key);
                }
                if(!empty($table_state['missing_indexes']))
                {
                    self::CreateMissingIndexes(
                        $definition,
                        $key,
                        $table_state['missing_indexes'],
                        $connection
                    );
                    $repaired[] = $key;
                    $inspection = self::Inspect($definition, $connection);
                }
            }

            $inspection = self::Inspect($definition, $connection);
            if(!$inspection['ready'])
            {
                throw new \RuntimeException('苗木安全表结构尚未完整，迁移停止');
            }

            $ledger = empty($ledger_row) ? self::NewLedger($definition) : $ledger_row['ledger'];
            self::AppendRun($ledger, $actor, $run_id, $created, $repaired);
            self::WriteLedger(
                $connection,
                empty($ledger_row) ? null : intval($ledger_row['id']),
                $definition,
                $ledger
            );
            self::AssertReady($connection);
            return DataReturn('苗木安全迁移完成', 0, [
                'schema_version' => self::SECURITY_SCHEMA_VERSION,
                'created'        => array_values($created),
                'repaired'       => array_values($repaired),
                'replayed'       => false,
            ]);
        } catch(\Throwable $e) {
            // CREATE/ALTER statements are intentionally forward-only.  A
            // failed run leaves the observed state for a later safe repair.
            return DataReturn($e->getMessage(), -1);
        } finally {
            if($connection !== null)
            {
                self::ReleaseExecutionLock($connection);
            }
        }
    }

    public static function AssertReady($connection = null)
    {
        $definition = self::Definition();
        $inspection = self::Inspect($definition, $connection);
        if(!$inspection['ready'])
        {
            throw new \RuntimeException('苗木安全写入未启用：请先完成 security schema v1 迁移');
        }
        if(self::ReadLedger($definition, $connection, false) === null)
        {
            throw new \RuntimeException('苗木安全写入未启用：迁移台账缺失');
        }
        return true;
    }

    private static function Definition()
    {
        $file = dirname(__DIR__).DIRECTORY_SEPARATOR.'security-schema-v1.json';
        if(!is_file($file))
        {
            throw new \RuntimeException('苗木安全结构清单不存在');
        }
        $raw = file_get_contents($file);
        $definition = ($raw === false) ? null : json_decode($raw, true);
        if(!is_array($definition)
            || intval($definition['schema_version'] ?? 0) !== self::MANIFEST_SCHEMA_VERSION
            || intval($definition['security_schema_version'] ?? 0) !== self::SECURITY_SCHEMA_VERSION)
        {
            throw new \RuntimeException('苗木安全结构清单版本无效');
        }
        if(empty($definition['tables'])
            || !is_array($definition['tables'])
            || array_keys($definition['tables']) !== self::TABLE_KEYS)
        {
            throw new \RuntimeException('苗木安全结构清单表集合无效');
        }
        foreach(self::TABLE_KEYS as $key)
        {
            self::ValidateTableDefinition($key, $definition['tables'][$key]);
        }
        if(($definition['ledger']['only_tag'] ?? '') !== 'plugins_nursery_security_schema_v1')
        {
            throw new \RuntimeException('苗木安全迁移台账标识无效');
        }
        $definition['payload_sha256'] = hash('sha256', $raw);
        return $definition;
    }

    private static function ValidateTableDefinition($key, $table)
    {
        if(!is_array($table)
            || !isset($table['logical_name'], $table['name'], $table['engine'], $table['charset'], $table['collation'])
            || !is_array($table['columns'])
            || !is_array($table['indexes']))
        {
            throw new \RuntimeException('苗木安全结构清单表定义无效：'.$key);
        }
        foreach(['logical_name', 'name', 'engine', 'charset', 'collation'] as $field)
        {
            if(!is_string($table[$field]) || $table[$field] === '')
            {
                throw new \RuntimeException('苗木安全结构清单字段无效：'.$key.'/'.$field);
            }
        }
        if(preg_match('/^[A-Za-z][A-Za-z0-9_]*$/D', $table['logical_name']) !== 1
            || preg_match('/^[A-Za-z0-9_]+$/D', $table['name']) !== 1)
        {
            throw new \RuntimeException('苗木安全结构清单名称无效：'.$key);
        }

        $column_names = [];
        foreach($table['columns'] as $column)
        {
            if(!is_array($column)
                || !isset($column['name'], $column['type'], $column['nullable'])
                || !array_key_exists('default', $column)
                || !isset($column['extra']))
            {
                throw new \RuntimeException('苗木安全结构清单列定义无效：'.$key);
            }
            if(!is_string($column['name'])
                || preg_match('/^[A-Za-z][A-Za-z0-9_]*$/D', $column['name']) !== 1
                || isset($column_names[$column['name']]))
            {
                throw new \RuntimeException('苗木安全结构清单列名称重复或无效：'.$key);
            }
            if(!is_string($column['type'])
                || preg_match('/^[A-Za-z0-9(), ]+$/D', $column['type']) !== 1
                || !is_bool($column['nullable'])
                || !is_string($column['extra']))
            {
                throw new \RuntimeException('苗木安全结构清单列属性无效：'.$key.'/'.$column['name']);
            }
            $column_names[$column['name']] = true;
        }

        $index_names = [];
        $has_primary = false;
        foreach($table['indexes'] as $index)
        {
            if(!is_array($index)
                || !isset($index['name'], $index['unique'], $index['columns'])
                || !is_array($index['columns'])
                || empty($index['columns']))
            {
                throw new \RuntimeException('苗木安全结构清单索引定义无效：'.$key);
            }
            if(!is_string($index['name'])
                || preg_match('/^[A-Za-z][A-Za-z0-9_]*$/D', $index['name']) !== 1
                || isset($index_names[$index['name']])
                || !is_bool($index['unique']))
            {
                throw new \RuntimeException('苗木安全结构清单索引名称重复或无效：'.$key);
            }
            foreach($index['columns'] as $column)
            {
                if(!is_string($column) || !isset($column_names[$column]))
                {
                    throw new \RuntimeException('苗木安全结构清单索引列不存在：'.$key.'/'.$index['name']);
                }
            }
            $index_names[$index['name']] = true;
            $has_primary = $has_primary || $index['name'] === 'PRIMARY';
        }
        if(!$has_primary)
        {
            throw new \RuntimeException('苗木安全结构清单缺少 PRIMARY：'.$key);
        }
    }

    /** Inspect both tables against the manifest using information_schema. */
    private static function Inspect($definition, $connection = null)
    {
        if($connection === null)
        {
            $connection = Db::connect();
        }
        $result = ['ready'=>true, 'tables'=>[]];
        foreach(self::TABLE_KEYS as $key)
        {
            $table = self::TableName($definition, $key);
            $table_rows = $connection->query(
                'SELECT ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?',
                [$table],
                true
            );
            if(empty($table_rows))
            {
                $result['ready'] = false;
                $result['tables'][$key] = [
                    'name'=>$table,
                    'exists'=>false,
                    'columns'=>false,
                    'indexes'=>false,
                    'foreign_keys'=>false,
                    'missing_indexes'=>[],
                ];
                continue;
            }

            $table_row = $table_rows[0];
            $expected = $definition['tables'][$key];
            $engine = strtolower((string) self::RowValue($table_row, 'ENGINE'));
            $collation = strtolower((string) self::RowValue($table_row, 'TABLE_COLLATION'));
            if($engine !== strtolower($expected['engine'])
                || $collation !== strtolower($expected['collation']))
            {
                throw new \RuntimeException('苗木安全表引擎或字符集排序规则不一致：'.$key);
            }

            $charset_rows = $connection->query(
                'SELECT DISTINCT CHARACTER_SET_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND CHARACTER_SET_NAME IS NOT NULL',
                [$table],
                true
            );
            foreach($charset_rows as $charset_row)
            {
                if(strtolower((string) self::RowValue($charset_row, 'CHARACTER_SET_NAME')) !== strtolower($expected['charset']))
                {
                    throw new \RuntimeException('苗木安全表字符集不一致：'.$key);
                }
            }

            $columns = self::Columns($connection, $table, $expected);
            if(!$columns['compatible'])
            {
                throw new \RuntimeException('苗木安全表字段结构不一致：'.$key);
            }
            $indexes = self::Indexes($connection, $table, $expected);
            if(!$indexes['compatible'])
            {
                throw new \RuntimeException('苗木安全表索引结构不一致：'.$key);
            }
            $foreign_keys = self::ForeignKeys($connection, $table);
            if(!empty($foreign_keys))
            {
                throw new \RuntimeException('苗木安全表不得建立外键：'.$key);
            }

            $ready = $columns['ready'] && $indexes['ready'];
            if(!$ready)
            {
                $result['ready'] = false;
            }
            $result['tables'][$key] = [
                'name'            => $table,
                'exists'          => true,
                'columns'         => $columns['ready'],
                'indexes'         => $indexes['ready'],
                'missing_indexes' => $indexes['missing'],
                'foreign_keys'    => false,
            ];
        }
        return $result;
    }

    private static function Columns($connection, $table, $definition)
    {
        $rows = $connection->query(
            'SELECT ORDINAL_POSITION,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? ORDER BY ORDINAL_POSITION',
            [$table],
            true
        );
        $actual = [];
        foreach($rows as $row)
        {
            $position = intval(self::RowValue($row, 'ORDINAL_POSITION'));
            if($position <= 0)
            {
                throw new \RuntimeException('苗木安全表列元数据无效：'.$table);
            }
            $actual[$position] = [
                'name'     => (string) self::RowValue($row, 'COLUMN_NAME'),
                'type'     => strtolower(trim((string) self::RowValue($row, 'COLUMN_TYPE'))),
                'nullable' => strtoupper((string) self::RowValue($row, 'IS_NULLABLE')) === 'YES',
                'default'  => self::RowValue($row, 'COLUMN_DEFAULT'),
                'extra'    => strtolower(trim((string) self::RowValue($row, 'EXTRA'))),
            ];
        }
        ksort($actual);
        $actual = array_values($actual);
        $required = $definition['columns'];
        $ready = count($actual) === count($required);
        if($ready)
        {
            foreach($required as $position=>$column)
            {
                $actual_column = $actual[$position] ?? null;
                if(!is_array($actual_column)
                    || $actual_column['name'] !== $column['name']
                    || $actual_column['type'] !== strtolower(trim($column['type']))
                    || $actual_column['nullable'] !== (bool) $column['nullable']
                    || $actual_column['extra'] !== strtolower(trim($column['extra']))
                    || !self::DefaultsEqual($actual_column['default'], $column['default']))
                {
                    return ['ready'=>false, 'compatible'=>false, 'actual'=>$actual];
                }
            }
        }
        // A count mismatch is considered structurally incomplete but still
        // compatible enough to report; Run refuses to add indexes until the
        // operator repairs the columns explicitly.
        return ['ready'=>$ready, 'compatible'=>true, 'actual'=>$actual];
    }

    private static function Indexes($connection, $table, $definition)
    {
        $rows = $connection->query(
            'SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? ORDER BY INDEX_NAME,SEQ_IN_INDEX',
            [$table],
            true
        );
        $actual = [];
        foreach($rows as $row)
        {
            $name = (string) self::RowValue($row, 'INDEX_NAME');
            $sequence = intval(self::RowValue($row, 'SEQ_IN_INDEX'));
            if($name === '' || $sequence <= 0)
            {
                throw new \RuntimeException('苗木安全表索引元数据无效：'.$table);
            }
            if(!isset($actual[$name]))
            {
                $actual[$name] = [
                    'unique'  => intval(self::RowValue($row, 'NON_UNIQUE')) === 0,
                    'columns' => [],
                ];
            }
            $actual[$name]['columns'][$sequence] = (string) self::RowValue($row, 'COLUMN_NAME');
        }
        foreach($actual as &$index)
        {
            ksort($index['columns']);
            $index['columns'] = array_values($index['columns']);
        }
        unset($index);

        $required_names = array_values(array_map(function($index) {
            return $index['name'];
        }, $definition['indexes']));
        $unknown_names = array_values(array_diff(array_keys($actual), $required_names));
        if(!empty($unknown_names))
        {
            return ['ready'=>false, 'compatible'=>false, 'actual'=>$actual, 'missing'=>[], 'unknown'=>$unknown_names];
        }

        $missing = [];
        foreach($definition['indexes'] as $required)
        {
            $name = $required['name'];
            if(!isset($actual[$name]))
            {
                $missing[] = $required;
                continue;
            }
            if($actual[$name]['unique'] !== (bool) $required['unique']
                || $actual[$name]['columns'] !== array_values($required['columns']))
            {
                return ['ready'=>false, 'compatible'=>false, 'actual'=>$actual, 'missing'=>$missing];
            }
        }
        return ['ready'=>empty($missing), 'compatible'=>true, 'actual'=>$actual, 'missing'=>$missing];
    }

    private static function DefaultsEqual($actual, $expected)
    {
        if($expected === null)
        {
            return $actual === null;
        }
        if($actual === null)
        {
            return false;
        }
        return (string) $actual === (string) $expected;
    }

    private static function ForeignKeys($connection, $table)
    {
        return $connection->query(
            'SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND REFERENCED_TABLE_NAME IS NOT NULL',
            [$table],
            true
        );
    }

    private static function TableName($definition, $key)
    {
        $logical = $definition['tables'][$key]['logical_name'];
        $table = Db::name($logical)->getTable();
        if(!is_string($table) || preg_match('/^[A-Za-z0-9_]+$/D', $table) !== 1)
        {
            throw new \RuntimeException('苗木安全数据表名称无效：'.$key);
        }
        return $table;
    }

    private static function CreateTable($definition, $key, $connection)
    {
        $table_definition = $definition['tables'][$key];
        $table = self::TableName($definition, $key);
        $parts = [];
        foreach($table_definition['columns'] as $column)
        {
            $line = '`'.$column['name'].'` '.strtoupper($column['type']).($column['nullable'] ? ' NULL' : ' NOT NULL');
            if(array_key_exists('default', $column) && $column['default'] !== null)
            {
                $line .= ' DEFAULT '.self::SqlLiteral($column['default']);
            } elseif($column['nullable']) {
                $line .= ' DEFAULT NULL';
            }
            if($column['extra'] !== '')
            {
                $line .= ' '.strtoupper($column['extra']);
            }
            $parts[] = $line;
        }
        foreach($table_definition['indexes'] as $index)
        {
            $columns = array_map(function($column) {
                return '`'.$column.'`';
            }, $index['columns']);
            $prefix = $index['name'] === 'PRIMARY'
                ? 'PRIMARY KEY'
                : ($index['unique'] ? 'UNIQUE KEY `'.$index['name'].'`' : 'KEY `'.$index['name'].'`');
            $parts[] = $prefix.' ('.implode(',', $columns).')';
        }
        $sql = 'CREATE TABLE IF NOT EXISTS `'.$table.'` ('.implode(',', $parts).') ENGINE='.$table_definition['engine'].' DEFAULT CHARACTER SET='.$table_definition['charset'].' COLLATE='.$table_definition['collation'].' ROW_FORMAT=DYNAMIC';
        $connection->execute($sql);
    }

    private static function CreateMissingIndexes($definition, $key, $missing, $connection)
    {
        $table = self::TableName($definition, $key);
        foreach($missing as $index)
        {
            $columns = array_map(function($column) {
                return '`'.$column.'`';
            }, $index['columns']);
            if($index['name'] === 'PRIMARY')
            {
                $prefix = 'ADD PRIMARY KEY';
            } elseif($index['unique']) {
                $prefix = 'ADD UNIQUE KEY `'.$index['name'].'`';
            } else {
                $prefix = 'ADD KEY `'.$index['name'].'`';
            }
            $connection->execute('ALTER TABLE `'.$table.'` '.$prefix.' ('.implode(',', $columns).')');
        }
    }

    private static function SqlLiteral($value)
    {
        if(is_int($value) || is_float($value))
        {
            return (string) $value;
        }
        if(is_bool($value))
        {
            return $value ? '1' : '0';
        }
        return "'".str_replace(["\\", "'"], ["\\\\", "\\'"], (string) $value)."'";
    }

    private static function ReadLedger($definition, $connection = null, $lock = false)
    {
        if($connection === null)
        {
            $connection = Db::connect();
        }
        $table = Db::name('Config')->getTable();
        if(!is_string($table) || preg_match('/^[A-Za-z0-9_]+$/D', $table) !== 1)
        {
            throw new \RuntimeException('苗木安全迁移台账表名称无效');
        }
        $sql = 'SELECT `id`,`value` FROM `'.$table.'` WHERE `only_tag`=? LIMIT 1';
        if($lock)
        {
            $sql .= ' FOR UPDATE';
        }
        $rows = $connection->query($sql, [$definition['ledger']['only_tag']], true);
        if(empty($rows))
        {
            return null;
        }
        $ledger = json_decode((string) self::RowValue($rows[0], 'value'), true);
        if(!is_array($ledger)
            || intval($ledger['schema_version'] ?? 0) !== self::SECURITY_SCHEMA_VERSION
            || intval($ledger['security_schema_version'] ?? 0) !== self::SECURITY_SCHEMA_VERSION
            || !isset($ledger['payload_sha256'])
            || !hash_equals($definition['payload_sha256'], (string) $ledger['payload_sha256']))
        {
            throw new \RuntimeException('苗木安全迁移台账无效或与清单不一致');
        }
        return [
            'id'     => intval(self::RowValue($rows[0], 'id')),
            'ledger' => $ledger,
        ];
    }

    private static function NewLedger($definition)
    {
        $tables = [];
        foreach(self::TABLE_KEYS as $key)
        {
            $table = $definition['tables'][$key];
            $tables[$key] = [
                'name'         => $table['name'],
                'column_count' => count($table['columns']),
                'index_names'  => array_values(array_map(function($index) {
                    return $index['name'];
                }, $table['indexes'])),
            ];
        }
        return [
            'schema_version'          => self::SECURITY_SCHEMA_VERSION,
            'security_schema_version' => self::SECURITY_SCHEMA_VERSION,
            'payload_sha256'          => $definition['payload_sha256'],
            'tables'                  => $tables,
            'runs'                    => [],
        ];
    }

    private static function WriteLedger($connection, $id, $definition, $ledger)
    {
        $value = json_encode($ledger, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
        if($value === false)
        {
            throw new \RuntimeException('苗木安全迁移台账编码失败');
        }
        $table = Db::name('Config')->getTable();
        $description = 'nursery 插件 security schema v1 的非敏感迁移台账';
        $data = [
            $value,
            $definition['ledger']['name'],
            $description,
            '',
            'common',
            $definition['ledger']['only_tag'],
            time(),
        ];
        if(empty($id))
        {
            $affected = $connection->execute(
                'INSERT INTO `'.$table.'` (`value`,`name`,`describe`,`error_tips`,`type`,`only_tag`,`upd_time`) VALUES (?,?,?,?,?,?,?)',
                $data
            );
            if($affected !== 1)
            {
                throw new \RuntimeException('苗木安全迁移台账写入失败');
            }
        } else {
            $affected = $connection->execute(
                'UPDATE `'.$table.'` SET `value`=?,`name`=?,`describe`=?,`error_tips`=?,`type`=?,`only_tag`=?,`upd_time`=? WHERE `id`=? AND `only_tag`=?',
                array_merge($data, [intval($id), $definition['ledger']['only_tag']])
            );
            if($affected < 0)
            {
                throw new \RuntimeException('苗木安全迁移台账更新失败');
            }
        }
    }

    private static function AppendRun(&$ledger, $actor, $run_id, $created, $repaired)
    {
        if(!isset($ledger['runs']) || !is_array($ledger['runs']))
        {
            $ledger['runs'] = [];
        }
        $ledger['runs'][] = [
            'run_id'   => $run_id,
            'actor'    => $actor,
            'created'  => array_values($created),
            'repaired' => array_values($repaired),
            'applied_at' => time(),
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
        if(!is_string($actor) || preg_match('/^[A-Za-z0-9._:@\/\-]{2,80}$/D', $actor) !== 1)
        {
            throw new \InvalidArgumentException('安全迁移 actor 格式无效');
        }
        if(!is_string($run_id) || preg_match('/^[A-Za-z0-9][A-Za-z0-9._:\-]{5,100}$/D', $run_id) !== 1)
        {
            throw new \InvalidArgumentException('安全迁移 run-id 格式无效');
        }
    }

    private static function AcquireExecutionLock()
    {
        $connection = Db::connect();
        $rows = $connection->query(
            "SELECT GET_LOCK('".self::EXECUTION_LOCK."', 30) AS acquired",
            [],
            true
        );
        if(empty($rows) || intval(self::RowValue($rows[0], 'acquired')) !== 1)
        {
            throw new \RuntimeException('无法获取苗木安全迁移串行锁');
        }
        return $connection;
    }

    private static function ReleaseExecutionLock($connection)
    {
        $rows = $connection->query(
            "SELECT RELEASE_LOCK('".self::EXECUTION_LOCK."') AS released",
            [],
            true
        );
        if(empty($rows) || intval(self::RowValue($rows[0], 'released')) !== 1)
        {
            throw new \RuntimeException('苗木安全迁移锁释放失败');
        }
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
}
?>
