<?php
declare(strict_types=1);

ini_set('display_errors', '0');
error_reporting(E_ALL);

const MIAOMU_ROOT = '/var/www/html';
const MIAOMU_SECRET = '/run/secrets/mysql_app_password';
const MIAOMU_SOCKET = '/run/miaomu-fpm/php-fpm.sock';
const MIAOMU_RELEASE_FILE = '/usr/local/share/miaomu/release-sha';

/**
 * @param array<string, bool|string> $checks
 */
function finishCheck(bool $ok, string $mode, array $checks, ?string $errorCode = null): never
{
    $payload = [
        'status' => $ok ? 'pass' : 'fail',
        'mode' => $mode,
        'checks' => $checks,
    ];
    if($errorCode !== null)
    {
        $payload['error_code'] = $errorCode;
    }

    $encoded = json_encode($payload, JSON_UNESCAPED_SLASHES);
    if($encoded === false)
    {
        $encoded = '{"status":"fail","error_code":"json_encode_failed"}';
    }
    fwrite($ok ? STDOUT : STDERR, $encoded.PHP_EOL);
    exit($ok ? 0 : 1);
}

/**
 * @param array<string, bool|string> $checks
 */
function requireCheck(
    bool $condition,
    string $name,
    string $mode,
    array &$checks,
    string $errorCode
): void
{
    $checks[$name] = $condition;
    if(!$condition)
    {
        finishCheck(false, $mode, $checks, $errorCode);
    }
}

/**
 * @param array<string, bool|string> $checks
 */
function runBuildChecks(string $mode, array &$checks): void
{
    requireCheck(
        PHP_VERSION_ID >= 80200 && PHP_VERSION_ID < 80300,
        'php_82',
        $mode,
        $checks,
        'php_version_invalid'
    );

    $requiredExtensions = [
        'ctype',
        'curl',
        'dom',
        'fileinfo',
        'filter',
        'gd',
        'hash',
        'iconv',
        'json',
        'libxml',
        'mbstring',
        'pdo',
        'pdo_mysql',
        'posix',
        'simplexml',
        'xml',
        'xmlreader',
        'xmlwriter',
        'zip',
        'zlib',
    ];
    foreach($requiredExtensions as $extension)
    {
        requireCheck(
            extension_loaded($extension),
            'extension_'.$extension,
            $mode,
            $checks,
            'php_extension_missing'
        );
    }

    requireCheck(
        function_exists('fsockopen'),
        'function_fsockopen',
        $mode,
        $checks,
        'fsockopen_missing'
    );
    requireCheck(
        function_exists('curl_init'),
        'function_curl_init',
        $mode,
        $checks,
        'curl_missing'
    );

    $gd = gd_info();
    requireCheck(
        ($gd['FreeType Support'] ?? false) === true,
        'gd_freetype',
        $mode,
        $checks,
        'gd_capability_missing'
    );
    requireCheck(
        ($gd['JPEG Support'] ?? false) === true,
        'gd_jpeg',
        $mode,
        $checks,
        'gd_capability_missing'
    );
    requireCheck(
        ($gd['PNG Support'] ?? false) === true,
        'gd_png',
        $mode,
        $checks,
        'gd_capability_missing'
    );

    $platformCheck = MIAOMU_ROOT.'/vendor/composer/platform_check.php';
    requireCheck(
        is_file($platformCheck),
        'composer_platform_file',
        $mode,
        $checks,
        'composer_platform_missing'
    );
    try
    {
        require $platformCheck;
        $checks['composer_platform'] = true;
    }
    catch(Throwable)
    {
        finishCheck(false, $mode, $checks, 'composer_platform_failed');
    }
}

/**
 * @param array<string, bool|string> $checks
 */
function runRuntimeChecks(string $mode, array &$checks, bool $requireSocket = true): void
{
    requireCheck(
        function_exists('posix_geteuid')
        && function_exists('posix_getegid')
        && posix_geteuid() === 10001
        && posix_getegid() === 10001,
        'application_identity',
        $mode,
        $checks,
        'application_identity_invalid'
    );

    $processStatus = @file_get_contents('/proc/self/status');
    requireCheck(
        is_string($processStatus)
        && preg_match('/^CapEff:\s*0+$/mD', $processStatus) === 1,
        'effective_capabilities_empty',
        $mode,
        $checks,
        'effective_capabilities_invalid'
    );

    $expectedRelease = getenv('MIAOMU_RELEASE_SHA');
    $release = @file_get_contents(MIAOMU_RELEASE_FILE);
    $release = $release === false ? '' : trim($release);
    requireCheck(
        is_string($expectedRelease)
        && preg_match('/^[0-9a-f]{40}$/D', $expectedRelease) === 1
        && hash_equals($expectedRelease, $release),
        'release_revision',
        $mode,
        $checks,
        'release_revision_invalid'
    );

    $writablePaths = [
        'runtime' => MIAOMU_ROOT.'/runtime',
        'uploads' => MIAOMU_ROOT.'/public/static/upload',
        'downloads' => MIAOMU_ROOT.'/public/download',
        'fpm_socket_directory' => '/run/miaomu-fpm',
        'tmp' => '/tmp',
    ];
    foreach($writablePaths as $name => $path)
    {
        requireCheck(
            is_dir($path) && is_writable($path),
            $name.'_writable',
            $mode,
            $checks,
            'writable_path_invalid'
        );
    }

    $readOnlyPaths = [
        'app_source' => MIAOMU_ROOT.'/app',
        'config_source' => MIAOMU_ROOT.'/config',
        'extend_source' => MIAOMU_ROOT.'/extend',
        'index_entry' => MIAOMU_ROOT.'/public/index.php',
        'admin_entry' => MIAOMU_ROOT.'/public/admin.php',
        'api_entry' => MIAOMU_ROOT.'/public/api.php',
    ];
    foreach($readOnlyPaths as $name => $path)
    {
        requireCheck(
            file_exists($path) && !is_writable($path),
            $name.'_readonly',
            $mode,
            $checks,
            'readonly_path_invalid'
        );
    }

    $databaseConfig = MIAOMU_ROOT.'/config/database.php';
    $databaseConfigStat = @lstat($databaseConfig);
    requireCheck(
        $databaseConfigStat !== false
        && is_file($databaseConfig)
        && !is_link($databaseConfig)
        && is_readable($databaseConfig)
        && !is_writable($databaseConfig)
        && ($databaseConfigStat['size'] ?? 0) > 0
        && ($databaseConfigStat['uid'] ?? -1) === 0
        && ($databaseConfigStat['gid'] ?? -1) === 10001
        && (($databaseConfigStat['mode'] ?? 0) & 0777) === 0440,
        'database_config_metadata',
        $mode,
        $checks,
        'database_config_invalid'
    );

    $eventPath = MIAOMU_ROOT.'/app/event.php';
    $eventStat = @lstat($eventPath);
    requireCheck(
        $eventStat !== false
        && is_file($eventPath)
        && !is_link($eventPath)
        && is_readable($eventPath)
        && !is_writable($eventPath)
        && ($eventStat['size'] ?? 0) > 0
        && ($eventStat['uid'] ?? -1) === 0
        && ($eventStat['gid'] ?? -1) === 10001
        && (($eventStat['mode'] ?? 0) & 0777) === 0440,
        'generated_event_metadata',
        $mode,
        $checks,
        'generated_event_invalid'
    );

    try
    {
        $pluginConfigJson = @file_get_contents(MIAOMU_ROOT.'/app/plugins/nursery/config.json');
        $pluginConfig = is_string($pluginConfigJson) ? json_decode($pluginConfigJson, true) : null;
        $events = require $eventPath;
        requireCheck(
            is_array($pluginConfig)
            && isset($pluginConfig['hook'])
            && is_array($pluginConfig['hook'])
            && is_array($events)
            && array_keys($events) === ['listen']
            && isset($events['listen'])
            && $events['listen'] === $pluginConfig['hook'],
            'nursery_event_bindings',
            $mode,
            $checks,
            'nursery_event_bindings_invalid'
        );
    }
    catch(Throwable)
    {
        finishCheck(false, $mode, $checks, 'nursery_event_bindings_invalid');
    }

    $secretStat = @lstat(MIAOMU_SECRET);
    requireCheck(
        $secretStat !== false
        && is_file(MIAOMU_SECRET)
        && !is_link(MIAOMU_SECRET)
        && ($secretStat['size'] ?? 0) > 0
        && ($secretStat['uid'] ?? -1) === 0
        && ($secretStat['gid'] ?? -1) === 10001
        && (($secretStat['mode'] ?? 0) & 0777) === 0440,
        'database_secret_metadata',
        $mode,
        $checks,
        'database_secret_invalid'
    );

    if($requireSocket)
    {
        $socketStat = @lstat(MIAOMU_SOCKET);
        requireCheck(
            $socketStat !== false
            && @filetype(MIAOMU_SOCKET) === 'socket'
            && ($socketStat['uid'] ?? -1) === 10001
            && ($socketStat['gid'] ?? -1) === 10001
            && (($socketStat['mode'] ?? 0) & 0777) === 0660,
            'fpm_socket_metadata',
            $mode,
            $checks,
            'fpm_socket_invalid'
        );
    } else {
        $checks['fpm_socket_metadata'] = 'deferred_until_fpm';
    }
}

/**
 * @param array<string, bool|string> $checks
 */
function runReadinessChecks(string $mode, array &$checks): void
{
    try
    {
        $config = require MIAOMU_ROOT.'/config/database.php';
        $mysql = $config['connections']['mysql'] ?? null;
        if(!is_array($mysql))
        {
            finishCheck(false, $mode, $checks, 'database_config_shape_invalid');
        }

        $prefix = $mysql['prefix'] ?? '';
        if(!is_string($prefix) || preg_match('/^[A-Za-z0-9_]+$/D', $prefix) !== 1)
        {
            finishCheck(false, $mode, $checks, 'database_prefix_invalid');
        }

        $connectionString = sprintf(
            'mysql:host=%s;port=%s;dbname=%s;charset=%s',
            (string)($mysql['hostname'] ?? ''),
            (string)($mysql['hostport'] ?? ''),
            (string)($mysql['database'] ?? ''),
            (string)($mysql['charset'] ?? '')
        );
        $pdo = new PDO(
            $connectionString,
            (string)($mysql['username'] ?? ''),
            (string)($mysql['password'] ?? ''),
            [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_TIMEOUT => 3,
                PDO::ATTR_EMULATE_PREPARES => true,
            ]
        );

        $table = $prefix.'config';
        $pdo->query('SELECT 1 FROM '.$table.' LIMIT 1');
        $checks['database_config_table'] = true;

        $statement = $pdo->prepare(
            'SELECT 1 FROM '.$table.' WHERE only_tag = ? LIMIT 1'
        );
        $statement->execute(['plugins_nursery_catalog_manifest']);
        requireCheck(
            $statement->fetchColumn() !== false,
            'nursery_catalog_manifest',
            $mode,
            $checks,
            'nursery_catalog_not_ready'
        );

        $enabledPlugins = $pdo->query(
            'SELECT plugins FROM '.$prefix.'plugins WHERE is_enable = 1 ORDER BY plugins'
        )->fetchAll(PDO::FETCH_COLUMN);
        requireCheck(
            $enabledPlugins === ['nursery'],
            'enabled_plugin_set',
            $mode,
            $checks,
            'enabled_plugin_set_invalid'
        );
    }
    catch(Throwable)
    {
        finishCheck(false, $mode, $checks, 'database_readiness_failed');
    }
}

$argument = $argv[1] ?? '--all';
$modeMap = [
    '--build' => 'build',
    '--runtime' => 'runtime',
    '--startup' => 'startup',
    '--readiness' => 'readiness',
    '--health' => 'health',
    '--all' => 'all',
];
if(!isset($modeMap[$argument]) || count($argv) > 2)
{
    finishCheck(false, 'argument', [], 'invalid_arguments');
}

$mode = $modeMap[$argument];
$checks = [];

if(in_array($mode, ['build', 'all'], true))
{
    runBuildChecks($mode, $checks);
}
if(in_array($mode, ['runtime', 'startup', 'health', 'all'], true))
{
    runRuntimeChecks($mode, $checks, $mode !== 'startup');
}
if(in_array($mode, ['readiness', 'startup', 'health', 'all'], true))
{
    runReadinessChecks($mode, $checks);
}

finishCheck(true, $mode, $checks);
