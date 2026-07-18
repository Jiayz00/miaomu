#!/usr/bin/env php
<?php
declare(strict_types=1);

// Build-time helper: retain only the fixed ShopXO table definition statements.
// INSERT records and account data are deliberately excluded from the runtime image.
if(PHP_SAPI !== 'cli' || !in_array(count($argv), [3, 4], true))
{
    fwrite(STDERR, "invalid arguments\n");
    exit(64);
}
$source = (string) $argv[1];
$destination = (string) $argv[2];
$manifestPath = isset($argv[3]) ? (string) $argv[3] : '';
$sql = @file_get_contents($source);
if($sql === false || $sql === '')
{
    fwrite(STDERR, "schema source unavailable\n");
    exit(66);
}
$statements = preg_split('/;[\r\n]+/', $sql) ?: [];
$kept = ["SET NAMES utf8mb4", "SET FOREIGN_KEY_CHECKS = 0"];
$created = 0;
$createdTables = [];
foreach($statements as $statement)
{
    $statement = preg_replace('/^\s*(?:\/\*.*?\*\/\s*|--[^\r\n]*(?:\r?\n|$)\s*)+/s', '', $statement) ?? '';
    $statement = trim($statement);
    if($statement === '')
    {
        continue;
    }
    if(preg_match('/^(DROP\s+TABLE\s+IF\s+EXISTS\s+`sxo_[A-Za-z0-9_]+`|CREATE\s+TABLE\s+`sxo_[A-Za-z0-9_]+`)/i', $statement) !== 1)
    {
        continue;
    }
    if(stripos($statement, 'CREATE TABLE') === 0)
    {
        $created++;
        if(preg_match('/^CREATE\s+TABLE\s+`(sxo_[A-Za-z0-9_]+)`/i', $statement, $match) === 1)
        {
            $createdTables[] = $match[1];
        }
    }
    $kept[] = $statement;
}
if($created < 80)
{
    fwrite(STDERR, "schema extraction incomplete\n");
    exit(65);
}
if($manifestPath !== '')
{
    if(!is_file($manifestPath) || is_link($manifestPath))
    {
        fwrite(STDERR, "schema manifest unavailable\n");
        exit(66);
    }
    $manifestJson = @file_get_contents($manifestPath);
    $manifest = $manifestJson === false ? null : json_decode($manifestJson, true);
    $expectedTables = is_array($manifest) ? ($manifest['tables'] ?? null) : null;
    if(
        !is_array($manifest)
        || intval($manifest['schema_version'] ?? 0) !== 1
        || intval($manifest['table_count'] ?? 0) !== count($createdTables)
        || !is_array($expectedTables)
        || count($expectedTables) !== count($createdTables)
        || count(array_unique(array_map('strval', $expectedTables))) !== count($expectedTables)
    )
    {
        fwrite(STDERR, "schema manifest invalid\n");
        exit(65);
    }
    $actualTables = array_values(array_unique(array_map('strval', $createdTables)));
    $expectedTables = array_values(array_map('strval', $expectedTables));
    sort($actualTables, SORT_STRING);
    sort($expectedTables, SORT_STRING);
    if($actualTables !== $expectedTables)
    {
        fwrite(STDERR, "schema manifest mismatch\n");
        exit(65);
    }
}
$payload = implode(";\n\n", $kept).";\n";
if(@file_put_contents($destination, $payload, LOCK_EX) !== strlen($payload))
{
    fwrite(STDERR, "schema output failed\n");
    exit(74);
}
chmod($destination, 0444);
