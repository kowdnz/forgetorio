# Gera dist\FactorioModpackLauncher\FactorioModpackLauncher.exe (PyInstaller, modo pasta).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = if (Test-Path ".venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
& $py -m pip install -e ".[dev]"
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Testes falharam; build cancelado." }
& $py -m PyInstaller --noconfirm --clean --windowed --name FactorioModpackLauncher `
    --paths src --collect-submodules keyring.backends `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtPdf --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtQuick `
    src\factorio_launcher\__main__.py
Write-Host "Pronto: dist\FactorioModpackLauncher\FactorioModpackLauncher.exe"
