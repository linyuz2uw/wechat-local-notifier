param(
    [string]$Version = "1.0.0",
    [string]$InnoSetupCompiler = ""
)

$ErrorActionPreference = "Stop"

function Find-InnoCompiler {
    param([string]$ExplicitPath)

    if ($ExplicitPath -and (Test-Path $ExplicitPath)) {
        return $ExplicitPath
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    $fromPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }

    throw "Cannot find Inno Setup compiler ISCC.exe. Install Inno Setup 6 or pass -InnoSetupCompiler."
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "==> Cleaning old build outputs"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force installer | Out-Null

Write-Host "==> Checking Python"
python --version

Write-Host "==> Installing/updating PyInstaller"
python -m pip install --upgrade pip pyinstaller
python -m pip install -r requirements.txt

Write-Host "==> Building windowed exe"
pyinstaller `
    --clean `
    --onefile `
    --noconsole `
    --name WeChatLocalNotifier `
    wechat_local_notifier.py

if (-not (Test-Path "dist\WeChatLocalNotifier.exe")) {
    throw "PyInstaller did not create dist\WeChatLocalNotifier.exe"
}

$iscc = Find-InnoCompiler -ExplicitPath $InnoSetupCompiler
Write-Host "==> Using Inno Setup: $iscc"

$env:APP_VERSION = $Version
& $iscc "installer.iss"

$installerPath = Join-Path $ProjectRoot "installer\WeChatLocalNotifierSetup-$Version.exe"
if (-not (Test-Path $installerPath)) {
    throw "Installer was not created: $installerPath"
}

Write-Host ""
Write-Host "Done: $installerPath"
Write-Host "This exe is the Windows installer you can distribute."
