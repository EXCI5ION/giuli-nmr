param(
    [string] $InstallerVersion = "",
    [switch] $SkipInstaller,
    [switch] $SkipSmokeTest,
    [switch] $SkipInstallerValidation
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$spec = Join-Path $PSScriptRoot "giuli.spec"
$smokeTest = Join-Path $PSScriptRoot "smoke_test.ps1"
$installerValidation = Join-Path $PSScriptRoot "validate_installer.ps1"
$executable = Join-Path $projectRoot "dist\GIULI\GIULI.exe"
$report = Join-Path $projectRoot "build\smoke-test.json"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "No existe el entorno virtual esperado: $python"
}

$versions = & $python -c "import PyInstaller, PySide6; print(PyInstaller.__version__); print(PySide6.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "No fue posible comprobar las dependencias de empaquetado."
}
if ($versions[0].Trim() -ne "6.22.2") {
    throw "Se requiere PyInstaller 6.22.2; se encontró $($versions[0])."
}
if ($versions[1].Trim() -ne "6.11.2") {
    throw "Se requiere PySide6 6.11.2; se encontró $($versions[1])."
}

$version = & $python -c "import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
if ($LASTEXITCODE -ne 0 -or -not $version) {
    throw "No fue posible obtener la versión desde pyproject.toml."
}
$version = $version.Trim()
if (-not $InstallerVersion) {
    $InstallerVersion = $version
}
if ($InstallerVersion -notmatch "^[0-9]+\.[0-9]+\.[0-9]+(?:-rc[0-9]+)?$") {
    throw "Versión de instalador no válida: $InstallerVersion"
}

$pythonBase = (& $python -c "import sys; print(sys.base_prefix)").Trim()
$windowsDir = [System.IO.Path]::GetFullPath($env:WINDIR)
$safePath = @(
    (Split-Path -Parent $python),
    $pythonBase,
    (Join-Path $pythonBase "Scripts"),
    (Join-Path $windowsDir "System32"),
    $windowsDir
) | Select-Object -Unique

$previousPath = $env:PATH
try {
    $env:PATH = $safePath -join ";"
    Push-Location $projectRoot
    try {
        & $python -m PyInstaller --noconfirm --clean $spec
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller terminó con código $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PATH = $previousPath
}

if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "PyInstaller no produjo el ejecutable esperado: $executable"
}

if (-not $SkipSmokeTest) {
    & $smokeTest -Executable $executable -ReportPath $report
}

if (-not $SkipInstaller) {
    $isccCandidates = @(
        "C:\Program Files\Inno Setup 7\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
    )
    $iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $iscc) {
        throw "No se encontró Inno Setup 7 (ISCC.exe)."
    }

    Push-Location $projectRoot
    try {
        & $iscc "/DMyAppVersion=$InstallerVersion" (Join-Path $PSScriptRoot "giuli.iss")
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup terminó con código $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    if (-not $SkipInstallerValidation) {
        $installer = Join-Path $projectRoot "dist-installer\GIULI-$InstallerVersion-windows-x64.exe"
        & $installerValidation -Installer $installer
    }
}

Write-Output "Empaquetado de GIULI $InstallerVersion completado."
