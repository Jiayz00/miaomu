$ErrorActionPreference = 'Stop'

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $Python) {
    Write-Error 'Python 3.11+ is required but python was not found on PATH.'
    exit 127
}

$SensitiveCommands = @('remote-actions', 'remote-exec', 'release-seal', 'release-check')
$HarnessScript = Join-Path $PSScriptRoot 'harness.py'
if ($args.Count -gt 0 -and $SensitiveCommands -contains [string]$args[0]) {
    & $Python.Source -I -S -B $HarnessScript @args
} else {
    & $Python.Source $HarnessScript @args
}
exit $LASTEXITCODE
