#!/usr/bin/env php
<?php
namespace think;

if(PHP_SAPI !== 'cli')
{
    fwrite(STDERR, "This command is CLI-only.\n");
    exit(2);
}

function NurseryFavoriteParseOptions($argv, $allowed)
{
    $options = [];
    for($index = 2; $index < count($argv); $index++)
    {
        $argument = $argv[$index];
        if(!is_string($argument) || substr($argument, 0, 2) !== '--')
        {
            throw new \InvalidArgumentException('Unexpected positional argument: '.(string) $argument);
        }
        $name = substr($argument, 2);
        if(!in_array($name, $allowed, true) || isset($options[$name]))
        {
            throw new \InvalidArgumentException('Unknown or duplicate option: --'.$name);
        }
        if(!isset($argv[$index+1]) || substr((string) $argv[$index+1], 0, 2) === '--')
        {
            throw new \InvalidArgumentException('Missing value for option: --'.$name);
        }
        $options[$name] = $argv[++$index];
    }
    return $options;
}

function NurseryFavoriteOutput($result)
{
    $json = json_encode($result, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_PRETTY_PRINT);
    if($json === false)
    {
        fwrite(STDERR, "Unable to encode command result.\n");
        exit(2);
    }
    fwrite(STDOUT, $json."\n");
    exit(isset($result['code']) && intval($result['code']) === 0 ? 0 : 1);
}

function NurseryFavoriteActions()
{
    return ['status', 'preflight', 'migrate'];
}

try {
    $action = isset($argv[1]) ? $argv[1] : '';
    if(!in_array($action, NurseryFavoriteActions(), true))
    {
        throw new \InvalidArgumentException('Action must be status, preflight, or migrate.');
    }
    $options = NurseryFavoriteParseOptions($argv, $action === 'migrate' ? ['actor', 'run-id'] : []);
    if($action === 'migrate' && (empty($options['actor']) || empty($options['run-id'])))
    {
        throw new \InvalidArgumentException('migrate requires --actor and --run-id.');
    }
} catch(\Throwable $e) {
    NurseryFavoriteOutput(['msg'=>$e->getMessage(), 'code'=>-1, 'data'=>null]);
}

try {
    $root = dirname(__DIR__);
    require $root.'/public/core.php';
    require $root.'/vendor/autoload.php';
    (new App($root))->initialize();
    if($action === 'status')
    {
        $result = \app\plugins\nursery\service\FavoriteMigration::Status();
    } elseif($action === 'preflight') {
        $result = \app\plugins\nursery\service\FavoriteMigration::Preflight();
    } else {
        $result = \app\plugins\nursery\service\FavoriteMigration::Run($options['actor'], $options['run-id']);
    }
} catch(\Throwable $e) {
    NurseryFavoriteOutput(['msg'=>$e->getMessage(), 'code'=>-1, 'data'=>null]);
}
NurseryFavoriteOutput($result);
?>
