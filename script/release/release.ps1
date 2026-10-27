$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'release.py') @args
exit $LASTEXITCODE
