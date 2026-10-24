# Inicia o launcher em modo desenvolvimento.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
}
$env:PYTHONPATH = "$PSScriptRoot\src"
& .\.venv\Scripts\pythonw.exe -m factorio_launcher
