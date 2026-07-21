param([string]$OutputDirectory = "release")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$output = Join-Path $root $OutputDirectory
$python = Join-Path $backend ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $backend ".venv\Scripts\pyinstaller.exe"
$cyclonedx = Join-Path $backend ".venv\Scripts\cyclonedx-py.exe"

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE. Close any running Vite/Node process and retry from a clean dependency install."
    }
}

foreach ($required in @($python, $pyinstaller, $cyclonedx)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing packaging dependency: $required. Install backend/requirements.lock into backend/.venv first."
    }
}

New-Item -ItemType Directory -Force -Path $output | Out-Null
Push-Location $root
try {
    npm ci
    Assert-LastExitCode "npm ci"
    npm run build
    Assert-LastExitCode "frontend build"
    Push-Location $backend
    try {
        & $pyinstaller --noconfirm --clean LocalVault.spec
        Assert-LastExitCode "PyInstaller"
        & $cyclonedx environment --output-file (Join-Path $output "sbom-python.cdx.json")
        Assert-LastExitCode "CycloneDX SBOM"
    } finally { Pop-Location }
    Copy-Item (Join-Path $root "package-lock.json") (Join-Path $output "package-lock.json")
    $archive = Join-Path $output "LocalVault-windows-x64.zip"
    Compress-Archive -Path (Join-Path $backend "dist\LocalVault\*") -DestinationPath $archive -Force
    Get-FileHash -Algorithm SHA256 $archive | ForEach-Object { "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($archive))" } | Set-Content -Encoding ascii (Join-Path $output "SHA256SUMS")
} finally { Pop-Location }
