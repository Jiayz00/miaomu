#!/usr/bin/env php
<?php
namespace think;

if(PHP_SAPI !== 'cli')
{
    fwrite(STDERR, "This command is CLI-only.\n");
    exit(2);
}

function NurseryCatalogParseOptions($argv, $allowed_flags)
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
        if(!array_key_exists($name, $allowed_flags) || array_key_exists($name, $options))
        {
            throw new \InvalidArgumentException('Unknown or duplicate option: --'.$name);
        }
        if($allowed_flags[$name] === true)
        {
            $options[$name] = true;
            continue;
        }
        if(!isset($argv[$index+1]) || substr((string) $argv[$index+1], 0, 2) === '--')
        {
            throw new \InvalidArgumentException('Missing value for option: --'.$name);
        }
        $options[$name] = $argv[++$index];
    }
    return $options;
}

function NurseryCatalogOutput($result)
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

try {
    if(!isset($argv[1]) || !in_array($argv[1], ['preflight', 'migrate', 'integrity'], true))
    {
        throw new \InvalidArgumentException('Action must be preflight, migrate, or integrity.');
    }
    $action = $argv[1];
    if($action === 'preflight')
    {
        $options = NurseryCatalogParseOptions($argv, ['mode'=>false]);
        $mode = isset($options['mode']) ? $options['mode'] : 'existing';
    } elseif($action === 'migrate') {
        $options = NurseryCatalogParseOptions($argv, ['mode'=>false, 'actor'=>false, 'run-id'=>false]);
        foreach(['mode', 'actor', 'run-id'] as $required)
        {
            if(empty($options[$required]))
            {
                throw new \InvalidArgumentException('migrate requires --'.$required.'.');
            }
        }
    } else {
        $options = NurseryCatalogParseOptions($argv, ['apply'=>true, 'actor'=>false, 'run-id'=>false, 'expected-items-sha256'=>false]);
        $apply = !empty($options['apply']);
        if($apply && (empty($options['actor']) || empty($options['run-id']) || empty($options['expected-items-sha256'])))
        {
            throw new \InvalidArgumentException('integrity --apply requires --actor, --run-id, and --expected-items-sha256.');
        }
    }
} catch(\Throwable $e) {
    NurseryCatalogOutput(['msg'=>$e->getMessage(), 'code'=>-1, 'data'=>null]);
}

try {
    $root = dirname(__DIR__);
    require $root.'/public/core.php';
    require $root.'/vendor/autoload.php';
    (new App($root))->initialize();

    if($action === 'preflight')
    {
        $result = \app\plugins\nursery\service\CatalogMigration::Preflight($mode);
    } elseif($action === 'migrate') {
        $result = \app\plugins\nursery\service\CatalogMigration::Run($options['mode'], $options['actor'], $options['run-id']);
    } else {
        $result = \app\plugins\nursery\service\CatalogIntegrity::Run($apply, isset($options['actor']) ? $options['actor'] : '', isset($options['run-id']) ? $options['run-id'] : '', isset($options['expected-items-sha256']) ? strtolower($options['expected-items-sha256']) : '');
    }
} catch(\Throwable $e) {
    NurseryCatalogOutput(['msg'=>$e->getMessage(), 'code'=>-1, 'data'=>null]);
}
NurseryCatalogOutput($result);
?>
