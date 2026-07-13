$ErrorActionPreference = 'Stop'

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $Python) {
    Write-Error 'Python 3.11+ is required but python was not found on PATH.'
    exit 127
}

& $Python.Source (Join-Path $PSScriptRoot 'harness.py') @args
exit $LASTEXITCODE
