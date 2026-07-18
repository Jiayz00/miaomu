#!/usr/bin/env php
<?php
declare(strict_types=1);

/**
 * Bootstrap the fixed ShopXO table shape on a disposable, empty database.
 *
 * The upstream dump is intentionally used as a schema source only.  INSERT,
 * transaction and account statements are ignored so demo users, products,
 * attachments and the default id=1 administrator never enter the deployment.
 * This script is one-way and refuses to run after any table exists.
 */

function ShopxoSchemaFinish(bool $ok, string $code, array $data = []): never
{
    $payload = [
        'status' => $ok ? 'pass' : 'fail',
        'code'   => $code,
        'data'   => $data,
    ];
    $json = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if($json === false)
    {
        $json = '{"status":"fail","code":"json_encode_failed"}';
    }
    fwrite($ok ? STDOUT : STDERR, $json.PHP_EOL);
    exit($ok ? 0 : 1);
}

function ShopxoSchemaSplit(string $sql): array
{
    $statements = [];
    $buffer = '';
    $quote = '';
    $length = strlen($sql);
    for($index = 0; $index < $length; $index++)
    {
        $character = $sql[$index];
        if($quote !== '')
        {
            $buffer .= $character;
            if($character === '\\' && $index + 1 < $length)
            {
                $buffer .= $sql[++$index];
                continue;
            }
            if($character === $quote)
            {
                if($index + 1 < $length && $sql[$index + 1] === $quote)
                {
                    $buffer .= $sql[++$index];
                } else {
                    $quote = '';
                }
            }
            continue;
        }
        if($character === "'" || $character === '"' || $character === '`')
        {
            $quote = $character;
            $buffer .= $character;
            continue;
        }
        if($character === ';')
        {
            $trimmed = trim($buffer);
            if($trimmed !== '')
            {
                $statements[] = $trimmed;
            }
            $buffer = '';
            continue;
        }
        $buffer .= $character;
    }
    $trimmed = trim($buffer);
    if($trimmed !== '')
    {
        $statements[] = $trimmed;
    }
    return $statements;
}

function ShopxoSchemaStripComments(string $statement): string
{
    $statement = preg_replace('/^\s*(?:\/\*.*?\*\/\s*|--[^\r\n]*(?:\r?\n|$)\s*)+/s', '', $statement) ?? '';
    return trim($statement);
}

function ShopxoSchemaConnection(): PDO
{
    $configPath = '/var/www/html/config/database.php';
    if(!is_file($configPath) || is_link($configPath))
    {
        throw new RuntimeException('database_config_unavailable');
    }
    $config = require $configPath;
    $name = (string) ($config['default'] ?? 'mysql');
    $connection = $config['connections'][$name] ?? null;
    if(!is_array($connection))
    {
        throw new RuntimeException('database_connection_unavailable');
    }
    $host = (string) ($connection['hostname'] ?? '');
    $port = (string) ($connection['hostport'] ?? '3306');
    $database = (string) ($connection['database'] ?? '');
    $username = (string) ($connection['username'] ?? '');
    $passphrase = (string) ($connection['password'] ?? '');
    if($host === '' || $database === '' || $username === '' || $passphrase === '')
    {
        throw new RuntimeException('database_connection_invalid');
    }
    $connectionString = 'mysql:host='.$host.';port='.$port.';dbname='.$database.';charset=utf8mb4';
    return new PDO($connectionString, $username, $passphrase, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_EMULATE_PREPARES   => false,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
}

if(PHP_SAPI !== 'cli' || count($argv) !== 4 || ($argv[1] ?? '') !== 'initialize')
{
    ShopxoSchemaFinish(false, 'invalid_arguments');
}
$actor = trim((string) ($argv[2] ?? ''));
$runId = (string) ($argv[3] ?? '');
if(preg_match('/^[A-Za-z0-9._-]{3,80}$/D', $actor) !== 1 || !str_starts_with($runId, '--run-id='))
{
    ShopxoSchemaFinish(false, 'invalid_arguments');
}
$runId = substr($runId, strlen('--run-id='));
if(preg_match('/^[A-Za-z0-9._-]{8,120}$/D', $runId) !== 1)
{
    ShopxoSchemaFinish(false, 'invalid_run_id');
}

$pdo = null;
$markerName = 'sxo_miaomu_schema_bootstrap';
$markerActive = false;
try {
    $pdo = ShopxoSchemaConnection();
    $database = (string) $pdo->query('SELECT DATABASE()')->fetchColumn();
    $sqlPath = '/usr/local/share/miaomu/shopxo-schema.sql';
    $sql = @file_get_contents($sqlPath);
    if($sql === false || $sql === '')
    {
        ShopxoSchemaFinish(false, 'schema_source_unavailable');
    }

    $statements = [];
    $schemaNames = [];
    foreach(ShopxoSchemaSplit($sql) as $statement)
    {
        $statement = ShopxoSchemaStripComments($statement);
        if($statement === '' || preg_match('/^(SET\s+(?:NAMES|FOREIGN_KEY_CHECKS)\b|DROP\s+TABLE\s+IF\s+EXISTS\s+`sxo_[A-Za-z0-9_]+`|CREATE\s+TABLE\s+`sxo_[A-Za-z0-9_]+`)/i', $statement) !== 1)
        {
            continue;
        }
        if(preg_match('/^CREATE\s+TABLE\s+`(sxo_[A-Za-z0-9_]+)`/i', $statement, $match) === 1)
        {
            $schemaNames[$match[1]] = true;
        }
        $statements[] = $statement;
    }
    $created = count($schemaNames);
    if($created < 80)
    {
        ShopxoSchemaFinish(false, 'schema_source_incomplete', ['created_tables' => $created]);
    }

    $tableRows = $pdo->query(
        'SELECT table_name FROM information_schema.tables WHERE table_schema = '.$pdo->quote($database)
    )->fetchAll(PDO::FETCH_COLUMN);
    $tableRows = array_values(array_filter(array_map('strval', is_array($tableRows) ? $tableRows : [])));
    $tableCount = count($tableRows);
    if($tableCount > 0)
    {
        if(!in_array($markerName, $tableRows, true))
        {
            ShopxoSchemaFinish(false, 'database_not_empty', ['table_count' => $tableCount]);
        }
        $markerRows = $pdo->query(
            'SELECT id,status,run_id,created_at FROM `'.$markerName.'` ORDER BY id'
        )->fetchAll();
        if(
            count($markerRows) !== 1 ||
            (int) ($markerRows[0]['id'] ?? 0) !== 1 ||
            (string) ($markerRows[0]['status'] ?? '') !== 'failed' ||
            (string) ($markerRows[0]['run_id'] ?? '') !== $runId ||
            (int) ($markerRows[0]['created_at'] ?? 0) <= 0
        )
        {
            ShopxoSchemaFinish(false, 'bootstrap_marker_not_retryable');
        }
        foreach($tableRows as $tableName)
        {
            if($tableName === $markerName)
            {
                continue;
            }
            if(!isset($schemaNames[$tableName]))
            {
                ShopxoSchemaFinish(false, 'bootstrap_unknown_table');
            }
            if(preg_match('/^sxo_[A-Za-z0-9_]+$/D', $tableName) !== 1)
            {
                ShopxoSchemaFinish(false, 'bootstrap_unknown_table');
            }
            $rowCount = (int) $pdo->query('SELECT COUNT(*) FROM `'.$tableName.'`')->fetchColumn();
            if($rowCount !== 0)
            {
                ShopxoSchemaFinish(false, 'bootstrap_partial_data_present');
            }
        }
        $pdo->exec('SET FOREIGN_KEY_CHECKS=0');
        foreach(array_reverse(array_keys($schemaNames)) as $tableName)
        {
            if(in_array($tableName, $tableRows, true))
            {
                $pdo->exec('DROP TABLE IF EXISTS `'.$tableName.'`');
            }
        }
        $pdo->exec('DROP TABLE `'.$markerName.'`');
        $pdo->exec('SET FOREIGN_KEY_CHECKS=1');
    }

    $pdo->exec('CREATE TABLE `'.$markerName.'` (id tinyint unsigned NOT NULL PRIMARY KEY, status varchar(16) NOT NULL, run_id varchar(120) NOT NULL, created_at int unsigned NOT NULL) ENGINE=InnoDB');
    $markerStatement = $pdo->prepare('INSERT INTO `'.$markerName.'` (id,status,run_id,created_at) VALUES (1,?,?,UNIX_TIMESTAMP())');
    $markerStatement->execute(['running', $runId]);
    $markerActive = true;

    $allowed = 0;
    foreach($statements as $statement)
    {
        $pdo->exec($statement);
        $allowed++;
    }

    $required = ['sxo_admin', 'sxo_config', 'sxo_goods', 'sxo_goods_category', 'sxo_goods_favor', 'sxo_plugins', 'sxo_role', 'sxo_power'];
    $placeholders = implode(',', array_fill(0, count($required), '?'));
    $check = $pdo->prepare('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ? AND table_name IN ('.$placeholders.')');
    $check->execute(array_merge([$database], $required));
    $requiredCount = (int) $check->fetchColumn();
    if($requiredCount !== count($required))
    {
        throw new RuntimeException('schema_incomplete');
    }

    // Seed only non-sensitive runtime defaults and a tiny reference-region
    // chain.  No upstream account, user, product, attachment, order or
    // plugin data is imported.  The placeholder administrator is disabled
    // until an operator sets a secret.
    $configRows = [
        ['苗木展示平台', '网站名称', 'home_site_name', 'home'],
        ['苗木展示平台', '站点标题', 'home_seo_site_title', 'home'],
        ['苗木,绿化,园林', '站点关键字', 'home_seo_site_keywords', 'home'],
        ['苗木商品展示、收藏与询价平台', '站点描述', 'home_seo_site_description', 'home'],
        ['1', 'web端站点状态', 'home_site_web_state', 'home'],
        ['1', 'web端首页状态', 'home_site_web_home_state', 'home'],
        ['1', 'web端PC状态', 'home_site_web_pc_state', 'home'],
        ['default', '默认模板', 'common_default_theme', 'common'],
        ['username', '注册方式', 'home_user_reg_type', 'home'],
        ['username', '登录方式', 'home_user_login_type', 'home'],
        ['0', '用户注册开启审核', 'common_register_is_enable_audit', 'common'],
        ['0', '获取验证码-开启图片验证码', 'common_img_verify_state', 'common'],
        ['Asia/Shanghai', '默认时区', 'common_timezone', 'common'],
        ['0', '链接模式', 'home_seo_url_model', 'home'],
        ['html', '伪静态后缀', 'home_seo_url_html_suffix', 'home'],
    ];
    $configStatement = $pdo->prepare(
        'INSERT INTO sxo_config (value,name,`describe`,error_tips,type,only_tag,upd_time) VALUES (?,?,?,?,?,?,UNIX_TIMESTAMP())'
    );
    foreach($configRows as $configRow)
    {
        $configStatement->execute([$configRow[0], $configRow[1], '', '', $configRow[3], $configRow[2]]);
    }
    $pdo->exec("INSERT INTO sxo_config (value,name,`describe`,error_tips,type,only_tag,upd_time) VALUES (SHA2(UUID(),256),'','', '', 'common','common_data_encryption_secret',UNIX_TIMESTAMP())");

    // These rows are public reference data, not a business/customer address.
    // They make the province/city/county selector and inquiry validation
    // usable without importing the upstream 3,400-row demo dataset.
    $regionStatement = $pdo->prepare(
        'INSERT INTO sxo_region (id,pid,name,level,letters,code,lng,lat,sort,is_enable,add_time,upd_time) VALUES (?,?,?,?,?,?,0,0,0,1,UNIX_TIMESTAMP(),0)'
    );
    foreach([
        [1, 0, '北京市', 1, '', '001'],
        [36, 1, '北京市', 2, '', '002'],
        [457, 36, '东城区', 3, '', '003'],
    ] as $regionRow)
    {
        $regionStatement->execute($regionRow);
    }
    $seedTags = array_column($configRows, 2);
    $seedPlaceholders = implode(',', array_fill(0, count($seedTags), '?'));
    $seedConfigCheck = $pdo->prepare(
        'SELECT COUNT(*) FROM sxo_config WHERE only_tag IN ('.$seedPlaceholders.')'
    );
    $seedConfigCheck->execute($seedTags);
    if((int) $seedConfigCheck->fetchColumn() !== count($seedTags))
    {
        throw new RuntimeException('runtime_config_seed_incomplete');
    }
    $seedRegionCount = (int) $pdo->query(
        "SELECT COUNT(*) FROM sxo_region WHERE id IN (1,36,457) AND is_enable=1"
    )->fetchColumn();
    if($seedRegionCount !== 3)
    {
        throw new RuntimeException('region_seed_incomplete');
    }
    $pdo->exec("INSERT INTO sxo_role (id,name,is_enable,add_time,upd_time) VALUES (10001,'苗木运营管理员',0,UNIX_TIMESTAMP(),0)");
    $pdo->exec("INSERT INTO sxo_admin (id,token,avatar,username,login_pwd,login_salt,mobile,email,gender,status,login_total,login_time,role_id,add_time,upd_time) VALUES (10001,'','','nursery_admin','','', '', '', 0, 1, 0, 0, 10001, UNIX_TIMESTAMP(), 0)");

    $pdo->exec('DROP TABLE `'.$markerName.'`');
    $markerActive = false;
    ShopxoSchemaFinish(true, 'shopxo_schema_ready', [
        'actor' => $actor,
        'run_id' => $runId,
        'created_tables' => $created,
        'executed_statements' => $allowed,
        'sample_rows_imported' => 0,
        'runtime_config_rows' => count($configRows),
        'reference_region_rows' => 3,
        'admin_id_one_imported' => false,
        'admin_seed_id' => 10001,
        'admin_login' => 'blocked_until_credentials_are_set',
    ]);
} catch(Throwable $exception) {
    if($pdo instanceof PDO && $markerActive)
    {
        try {
            $pdo->exec("UPDATE `{$markerName}` SET status='failed' WHERE id=1");
        } catch(Throwable $ignored) {
        }
    }
    ShopxoSchemaFinish(false, 'schema_bootstrap_failed');
}
