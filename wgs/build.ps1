$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    python -m PyInstaller --noconfirm --clean --onedir --console --name sm64ds-server --paths . --distpath wgs/dist --workpath wgs/build --specpath wgs wgs/server.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    Copy-Item wgs/server.example.json wgs/dist/sm64ds-server/server.json
    Copy-Item LICENSE wgs/dist/sm64ds-server/LICENSE
} finally {
    Pop-Location
}
