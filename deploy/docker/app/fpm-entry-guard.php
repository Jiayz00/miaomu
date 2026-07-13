<?php
declare(strict_types=1);

if(PHP_SAPI !== 'fpm-fcgi')
{
    return;
}

$deny = static function(string $code): never
{
    http_response_code(404);
    error_log('[miaomu-fpm-guard] '.$code);
    exit;
};

foreach(['PATH_INFO', 'ORIG_PATH_INFO'] as $pathInfoKey)
{
    $pathInfo = $_SERVER[$pathInfoKey] ?? '';
    if(is_string($pathInfo) && $pathInfo !== '')
    {
        $deny('path_info_rejected');
    }
}

$scriptFilename = $_SERVER['SCRIPT_FILENAME'] ?? '';
if(!is_string($scriptFilename) || $scriptFilename === '' || str_contains($scriptFilename, "\0"))
{
    $deny('script_missing');
}

$resolvedScript = realpath($scriptFilename);
if($resolvedScript === false)
{
    $deny('script_unresolved');
}

$allowedScripts = [];
foreach([
    '/var/www/html/public/index.php',
    '/var/www/html/public/admin.php',
    '/var/www/html/public/api.php',
] as $entry)
{
    $resolvedEntry = realpath($entry);
    if($resolvedEntry === false)
    {
        $deny('entry_unresolved');
    }
    $allowedScripts[$resolvedEntry] = true;
}

if(!isset($allowedScripts[$resolvedScript]))
{
    $deny('script_rejected');
}
