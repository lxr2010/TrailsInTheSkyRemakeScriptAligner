<#
.SYNOPSIS
    将单语言的 script.pac 拆解为 scena_data_*.json（KuroTools 路线）。

.DESCRIPTION
    完整流程：
      1) 解包 PAC 得到 script/scena/*.dat
      2) 用 dat2py.py 反编译 .dat -> .py
      3) 用 scena_voice_kuro_extractor.py 提取 Cmd_text_00/06
      最终输出 scena_data_<lang>.json / *_Command.json / *_add_struct.json。

    所有路径均通过参数传入，脚本不假设任何固定绝对路径。

.PARAMETER PacFile
    script.pac 的完整路径（必需）。

.PARAMETER Language
    语言标签 jp 或 sc，决定输出文件名 scena_data_<lang>*.json（必需）。

.PARAMETER ExtractPacScript
    sky_extract_pac.py 的路径（必需）。

.PARAMETER Dat2PyScript
    dat2py.py 的路径（必需）。

.PARAMETER ExtractorScript
    scena_voice_kuro_extractor.py 的路径。省略时默认取本脚本同目录下的同名文件。

.PARAMETER OutputDir
    输出 scena_data_*.json 的目录，默认当前目录。

.PARAMETER WorkDir
    临时工作目录，默认在系统临时目录下自动创建。

.EXAMPLE
    .\decompile_pac.ps1 -PacFile "D:\game\script.pac" -Language jp `
        -ExtractPacScript "C:\tools\kuro_dlc_tool\sky_extract_pac.py" `
        -Dat2PyScript "C:\tools\KuroTools\dat2py.py" `
        -OutputDir ".\data"
#>
param(
    [Parameter(Mandatory = $true)][string]$PacFile,
    [Parameter(Mandatory = $true)][ValidateSet("jp", "sc")][string]$Language,
    [Parameter(Mandatory = $true)][string]$ExtractPacScript,
    [Parameter(Mandatory = $true)][string]$Dat2PyScript,
    [string]$ExtractorScript = "",
    [string]$OutputDir = ".",
    [string]$WorkDir = "",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

# ---- 路径解析（全部转为绝对路径，避免 Push-Location 后失效）----
$PacFile = (Resolve-Path $PacFile).Path
$ExtractPacScript = (Resolve-Path $ExtractPacScript).Path
$Dat2PyScript = (Resolve-Path $Dat2PyScript).Path
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}
$OutputDir = (Resolve-Path $OutputDir).Path

if (-not $ExtractorScript) {
    $ExtractorScript = Join-Path $PSScriptRoot "scena_voice_kuro_extractor.py"
}
if (-not (Test-Path $ExtractorScript)) { throw "提取脚本不存在: $ExtractorScript" }
$ExtractorScript = (Resolve-Path $ExtractorScript).Path

# ---- 工作目录 ----
if (-not $WorkDir) {
    $WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ("sora_align_" + [System.Guid]::NewGuid().ToString("N"))
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Write-Host "工作目录: $WorkDir"

# ---- 反编译依赖 zstandard（dat2py.py 需要）----
& $Python -c "import zstandard" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "未检测到 zstandard，正在安装..."
    & $Python -m pip install zstandard
    if ($LASTEXITCODE -ne 0) { throw "zstandard 安装失败" }
}

# ---- [1/3] 解包 PAC ----
# sky_extract_pac.py 会 chdir 到自身所在目录再解包，所以复制到工作目录运行，
# 让产物落在 $WorkDir/script/scena/ 下。
$unpackScript = Join-Path $WorkDir "sky_extract_pac.py"
Copy-Item $ExtractPacScript $unpackScript
Write-Host "[1/3] 解包 PAC: $PacFile"
Push-Location $WorkDir
try {
    & $Python $unpackScript $PacFile
    if ($LASTEXITCODE -ne 0) { throw "解包 PAC 失败" }
} finally {
    Pop-Location
}

$datDir = Join-Path $WorkDir "script\scena"
if (-not (Test-Path $datDir)) { throw "未找到解包产物目录: $datDir" }
$datFiles = @(Get-ChildItem $datDir -Filter *.dat -File)
if ($datFiles.Count -eq 0) { throw "未在 $datDir 找到任何 .dat 文件" }
Write-Host "  找到 $($datFiles.Count) 个 .dat 文件"

# ---- [2/3] 反编译 .dat -> .py ----
$pyDir = Join-Path $WorkDir "py"
New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
Write-Host "[2/3] 反编译 .dat -> .py（输出到 $pyDir）"
Push-Location $pyDir
try {
    $i = 0
    foreach ($dat in $datFiles) {
        $i++
        if ($i % 50 -eq 0) { Write-Host "  进度: $i / $($datFiles.Count)" }
        & $Python $Dat2PyScript --decompile True --markers False $dat.FullName
        if ($LASTEXITCODE -ne 0) { throw "反编译失败: $($dat.Name)" }
    }
} finally {
    Pop-Location
}
$pyFiles = @(Get-ChildItem $pyDir -Filter *.py -File)
Write-Host "  生成 $($pyFiles.Count) 个 .py 文件"

# ---- [3/3] 提取台词 ----
Write-Host "[3/3] 提取 Cmd_text_00/06 -> scena_data_${Language}*.json"
& $Python $ExtractorScript --input-dir $pyDir --language $Language --output-dir $OutputDir
if ($LASTEXITCODE -ne 0) { throw "提取失败" }

Write-Host ""
Write-Host "完成。输出文件:"
Get-ChildItem $OutputDir -Filter "scena_data_${Language}*.json" | ForEach-Object {
    Write-Host ("  {0}  ({1:N0} 字节)" -f $_.FullName, $_.Length)
}
Write-Host ""
Write-Host "工作目录（如需排查可查看，可手动删除）: $WorkDir"
