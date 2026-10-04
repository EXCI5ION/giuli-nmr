param(
    [Parameter(Mandatory = $true)]
    [string] $Installer,
    [string] $TestDirectory = "",
    [string] $ReportPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$installerPath = [System.IO.Path]::GetFullPath($Installer)

if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "No existe el instalador: $installerPath"
}

if (-not $TestDirectory) {
    $TestDirectory = Join-Path $projectRoot ".install-smoke"
}
$testPath = [System.IO.Path]::GetFullPath($TestDirectory)
$projectPrefix = $projectRoot.TrimEnd('\') + '\'
if (-not $testPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "La instalación de prueba debe quedar dentro del proyecto: $testPath"
}
if (Test-Path -LiteralPath $testPath) {
    throw "El destino de prueba ya existe y no se eliminará automáticamente: $testPath"
}

if (-not $ReportPath) {
    $ReportPath = Join-Path $projectRoot "build\installed-smoke-test.json"
}
$logPath = Join-Path $projectRoot "build\installer-smoke.log"
$uninstaller = Join-Path $testPath "unins000.exe"

try {
    $installProcess = Start-Process -FilePath $installerPath -ArgumentList @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/DIR=`"$testPath`"",
        "/LOG=`"$logPath`""
    ) -PassThru -Wait -WindowStyle Hidden

    if ($installProcess.ExitCode -ne 0) {
        throw "El instalador terminó con código $($installProcess.ExitCode)."
    }

    $installedExecutable = Join-Path $testPath "GIULI.exe"
    & (Join-Path $PSScriptRoot "smoke_test.ps1") `
        -Executable $installedExecutable `
        -ReportPath $ReportPath
}
finally {
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        $uninstallProcess = Start-Process -FilePath $uninstaller -ArgumentList @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART"
        ) -PassThru -Wait -WindowStyle Hidden

        if ($uninstallProcess.ExitCode -ne 0) {
            Write-Warning "El desinstalador terminó con código $($uninstallProcess.ExitCode)."
        }
    }
}

if (Test-Path -LiteralPath $testPath) {
    throw "La desinstalación de prueba no retiró el directorio: $testPath"
}

Write-Output "Instalador validado y copia de prueba desinstalada."
