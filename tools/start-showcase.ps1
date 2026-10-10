$ErrorActionPreference = 'Stop'
$showcaseRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $showcaseRoot
try {
    & '.\.venv\Scripts\python.exe' 'tools/run_showcase.py' @args
    if ($LASTEXITCODE -ne 0) { throw 'Showcase exited with an error. See var/showcase-* logs.' }
} finally {
    Pop-Location
}
