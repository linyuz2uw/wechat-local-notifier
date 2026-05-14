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

    throw "找不到 Inno Setup 编译器 ISCC.exe。请安装 Inno Setup 6，或用 -InnoSetupCompiler 指定 ISCC.exe 路径。"
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "==> 清理旧构建产物"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force installer | Out-Null

Write-Host "==> 检查 Python"
python --version

Write-Host "==> 安装/更新 PyInstaller"
python -m pip install --upgrade pip pyinstaller

Write-Host "==> 构建无控制台 exe"
pyinstaller `
    --clean `
    --onefile `
    --noconsole `
    --name WeChatLocalNotifier `
    wechat_local_notifier.py

if (-not (Test-Path "dist\WeChatLocalNotifier.exe")) {
    throw "PyInstaller 未生成 dist\WeChatLocalNotifier.exe"
}

$iscc = Find-InnoCompiler -ExplicitPath $InnoSetupCompiler
Write-Host "==> 使用 Inno Setup: $iscc"

$env:APP_VERSION = $Version
& $iscc "installer.iss"

$installerPath = Join-Path $ProjectRoot "installer\WeChatLocalNotifierSetup-$Version.exe"
if (-not (Test-Path $installerPath)) {
    throw "安装包未生成：$installerPath"
}

Write-Host ""
Write-Host "完成：$installerPath"
Write-Host "这个 exe 就是可以发给自己下载/双击安装的 Windows 安装包。"
