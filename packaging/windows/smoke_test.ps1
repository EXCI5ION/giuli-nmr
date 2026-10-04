param(
    [Parameter(Mandatory = $true)]
    [string] $Executable,
    [string] $ReportPath = ""
)

$ErrorActionPreference = "Stop"
$executablePath = [System.IO.Path]::GetFullPath($Executable)

if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "No existe el ejecutable: $executablePath"
}

$applicationDir = Split-Path -Parent $executablePath
$internalDir = Join-Path $applicationDir "_internal"
$forbiddenIcu = @(
    Get-Item -LiteralPath (Join-Path $internalDir "icuuc.dll") -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $internalDir -Filter "icudt*.dll" -File -ErrorAction SilentlyContinue
)

if ($forbiddenIcu.Count -gt 0) {
    $paths = ($forbiddenIcu.FullName -join ", ")
    throw "El paquete contiene ICU prohibidas junto al ejecutable: $paths"
}

$previousRenderer = $env:GIULI_RENDERER
$env:GIULI_RENDERER = "raster"
$process = $null

try {
    $process = Start-Process -FilePath $executablePath -PassThru -WindowStyle Hidden
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    $modules = @()
    $qtCore = @()
    $qtWidgets = @()

    do {
        Start-Sleep -Milliseconds 250
        $process.Refresh()
        if ($process.HasExited) {
            throw "GIULI terminó durante el arranque con código $($process.ExitCode)."
        }
        $modules = @($process.Modules)
        $qtCore = @($modules | Where-Object { $_.ModuleName -ieq "QtCore.pyd" })
        $qtWidgets = @($modules | Where-Object { $_.ModuleName -ieq "QtWidgets.pyd" })
    } until (
        ($qtCore.Count -eq 1 -and $qtWidgets.Count -eq 1) -or
        [DateTime]::UtcNow -ge $deadline
    )

    if ($qtCore.Count -ne 1 -or $qtWidgets.Count -ne 1) {
        throw "GIULI abrió, pero no fue posible verificar QtCore.pyd y QtWidgets.pyd."
    }

    $windowsRoot = [System.IO.Path]::GetFullPath($env:WINDIR).TrimEnd('\')
    $loadedIcu = @($modules | Where-Object { $_.ModuleName -match "^icu.*\.dll$" })
    $foreignLoadedIcu = @(
        $loadedIcu | Where-Object {
            $modulePath = [System.IO.Path]::GetFullPath($_.FileName)
            -not $modulePath.StartsWith($windowsRoot, [StringComparison]::OrdinalIgnoreCase) -and
            $modulePath -notmatch "[\\/]PySide6[\\/]"
        }
    )

    if ($foreignLoadedIcu.Count -gt 0) {
        $paths = ($foreignLoadedIcu.FileName -join ", ")
        throw "GIULI cargó una ICU desde una ubicación no permitida: $paths"
    }

    $report = [ordered]@{
        executable = $executablePath
        process_started = $true
        process_stable = $true
        window_handle_observed = ($process.MainWindowHandle -ne 0)
        qt_core = $qtCore[0].FileName
        qt_widgets = $qtWidgets[0].FileName
        loaded_icu = @($loadedIcu | ForEach-Object { $_.FileName })
        forbidden_packaged_icu = @()
    }

    $json = $report | ConvertTo-Json -Depth 4
    if ($ReportPath) {
        $resolvedReport = [System.IO.Path]::GetFullPath($ReportPath)
        $reportDirectory = Split-Path -Parent $resolvedReport
        New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
        Set-Content -LiteralPath $resolvedReport -Value $json -Encoding utf8
    }
    Write-Output $json
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }

    if ($null -eq $previousRenderer) {
        Remove-Item Env:GIULI_RENDERER -ErrorAction SilentlyContinue
    }
    else {
        $env:GIULI_RENDERER = $previousRenderer
    }
}
