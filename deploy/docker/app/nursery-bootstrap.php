#!/usr/bin/env php
<?php
declare(strict_types=1);

namespace think;

use app\plugins\nursery\service\CatalogMigration;
use app\service\PluginsAdminService;
use think\facade\Db;

function NurseryBootstrapFinish(bool $ok, string $code, array $data = []): never
{
    $payload = [
        'status' => $ok ? 'pass' : 'fail',
        'code' => $code,
        'data' => $data,
    ];
    $json = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if($json === false)
    {
        $json = '{"status":"fail","code":"json_encode_failed"}';
    }
    fwrite($ok ? STDOUT : STDERR, $json.PHP_EOL);
    exit($ok ? 0 : 1);
}

function NurseryBootstrapEventMatches(string $root): bool
{
    $eventPath = $root.'/app/event.php';
    $configPath = $root.'/app/plugins/nursery/config.json';
    if(!is_file($eventPath) || is_link($eventPath) || !is_file($configPath))
    {
        return false;
    }
    $configJson = @file_get_contents($configPath);
    if($configJson === false)
    {
        return false;
    }
    $config = json_decode($configJson, true);
    if(!is_array($config) || !isset($config['hook']) || !is_array($config['hook']))
    {
        return false;
    }
    $events = require $eventPath;
    return is_array($events)
        && array_keys($events) === ['listen']
        && isset($events['listen'])
        && $events['listen'] === $config['hook'];
}

if(PHP_SAPI !== 'cli' || count($argv) !== 5 || ($argv[1] ?? '') !== 'initialize')
{
    NurseryBootstrapFinish(false, 'invalid_arguments');
}
if(($argv[2] ?? '') !== '--actor' || ($argv[4] ?? '') === '' || !str_starts_with($argv[4], '--run-id='))
{
    NurseryBootstrapFinish(false, 'invalid_arguments');
}
$actor = trim((string) $argv[3]);
$runId = substr((string) $argv[4], strlen('--run-id='));
if($actor === '' || preg_match('/^[A-Za-z0-9._-]{3,80}$/D', $actor) !== 1)
{
    NurseryBootstrapFinish(false, 'invalid_actor');
}
if(preg_match('/^[A-Za-z0-9._-]{8,120}$/D', $runId) !== 1)
{
    NurseryBootstrapFinish(false, 'invalid_run_id');
}

$root = '/var/www/html';
$eventPath = $root.'/app/event.php';
$eventStat = @lstat($eventPath);
if(
    $eventStat === false
    || !is_file($eventPath)
    || is_link($eventPath)
    || !is_writable($eventPath)
    || ($eventStat['uid'] ?? -1) !== 0
    || ($eventStat['gid'] ?? -1) !== 10001
    || (($eventStat['mode'] ?? 0) & 0777) !== 0660
)
{
    NurseryBootstrapFinish(false, 'event_bootstrap_metadata_invalid');
}

$safeEventStub = "<?php\nreturn [];\n";
$written = @file_put_contents($eventPath, $safeEventStub, LOCK_EX);
if($written !== strlen($safeEventStub))
{
    NurseryBootstrapFinish(false, 'event_stub_write_failed');
}
clearstatcache(true, $eventPath);

ini_set('display_errors', '0');
error_reporting(E_ALL);

try {
    require $root.'/public/core.php';
    require $root.'/vendor/autoload.php';
    (new App($root))->initialize();

    $enabled = Db::name('Plugins')->where(['is_enable'=>1])->column('plugins');
    $enabled = array_values(array_unique(array_map('strval', is_array($enabled) ? $enabled : [])));
    $unexpected = array_values(array_diff($enabled, ['nursery']));
    if(!empty($unexpected))
    {
        NurseryBootstrapFinish(false, 'unexpected_enabled_plugin');
    }

    $plugin = Db::name('Plugins')->where(['plugins'=>'nursery'])->find();
    if(empty($plugin))
    {
        $install = PluginsAdminService::PluginsInstall([
            'id' => 'nursery',
            'nursery_catalog_mode' => 'existing',
        ]);
        if(!is_array($install) || intval($install['code'] ?? -1) !== 0)
        {
            NurseryBootstrapFinish(false, 'nursery_install_failed');
        }
        $plugin = Db::name('Plugins')->where(['plugins'=>'nursery'])->find();
    }

    $enabledState = intval($plugin['is_enable'] ?? 0);
    if($enabledState === 1 && !NurseryBootstrapEventMatches($root))
    {
        $disable = PluginsAdminService::PluginsStatusUpdate(['id'=>'nursery', 'state'=>0]);
        if(!is_array($disable) || intval($disable['code'] ?? -1) !== 0)
        {
            NurseryBootstrapFinish(false, 'nursery_event_reset_failed');
        }
        $enabledState = 0;
    }
    if($enabledState !== 1)
    {
        $enable = PluginsAdminService::PluginsStatusUpdate(['id'=>'nursery', 'state'=>1]);
        if(!is_array($enable) || intval($enable['code'] ?? -1) !== 0)
        {
            NurseryBootstrapFinish(false, 'nursery_enable_failed');
        }
    }
    if(!NurseryBootstrapEventMatches($root))
    {
        NurseryBootstrapFinish(false, 'nursery_event_invalid');
    }

    $catalog = CatalogMigration::Run('existing', $actor, $runId);
    if(!is_array($catalog) || intval($catalog['code'] ?? -1) !== 0)
    {
        NurseryBootstrapFinish(false, 'nursery_catalog_failed');
    }

    $enabled = Db::name('Plugins')->where(['is_enable'=>1])->column('plugins');
    $enabled = array_values(array_unique(array_map('strval', is_array($enabled) ? $enabled : [])));
    sort($enabled, SORT_STRING);
    if($enabled !== ['nursery'])
    {
        NurseryBootstrapFinish(false, 'enabled_plugin_set_invalid');
    }
} catch(\Throwable) {
    NurseryBootstrapFinish(false, 'bootstrap_failed');
}

NurseryBootstrapFinish(true, 'nursery_ready', ['plugin'=>'nursery', 'catalog'=>'existing']);
