param([string]$OutputDirectory = "release")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$output = Join-Path $root $OutputDirectory
New-Item -ItemType Directory -Force -Path $output | Out-Null
Push-Location $root
try {
    npm ci
    npm run build
    Push-Location $backend
    try {
        pyinstaller --noconfirm --clean LocalVault.spec
        cyclonedx-py environment --output-file (Join-Path $output "sbom-python.cdx.json")
    } finally { Pop-Location }
    Copy-Item (Join-Path $root "package-lock.json") (Join-Path $output "package-lock.json")
    $archive = Join-Path $output "LocalVault-windows-x64.zip"
    Compress-Archive -Path (Join-Path $backend "dist\LocalVault\*") -DestinationPath $archive -Force
    Get-FileHash -Algorithm SHA256 $archive | ForEach-Object { "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($archive))" } | Set-Content -Encoding ascii (Join-Path $output "SHA256SUMS")
} finally { Pop-Location }
