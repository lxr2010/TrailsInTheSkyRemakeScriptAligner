<#
.SYNOPSIS
    一键运行台词匹配（fc / sc / 3rd）。

.DESCRIPTION
    自动下载 EVO 侧数据（script_data_*.json / additional_voice_*.json）
    以及说话人映射（speaker_map_*.json，可选），
    然后调用 main.py 完成匹配，输出 match_result_<game>.csv。

    需要用户自备 Remake 侧数据（由 decompile_pac.ps1 生成）：
      - scena_data_jp_Command.json（必需）
      - scena_data_sc_Command.json（可选，中文翻译）

.PARAMETER Game
    目标作品：fc / sc / 3rd（必需）。

.PARAMETER RemakeJp
    Remake 日文数据路径，默认 scena_data_jp_Command.json。

.PARAMETER Translation
    Remake 中文翻译数据路径，默认 scena_data_sc_Command.json（不存在则自动跳过）。

.PARAMETER OutputDir
    EVO 侧数据与最终 CSV 的输出目录，默认当前目录。

.PARAMETER SkipDownload
    跳过下载，要求 EVO 侧数据文件已存在于 OutputDir。

.PARAMETER Fresh
    运行前清空共享的 LLM 缓存（llm_*.json），避免不同作品间缓存串味。

.EXAMPLE
    .\run_match.ps1 -Game sc -Fresh
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet("fc", "sc", "3rd")][string]$Game,
    [string]$RemakeJp = "scena_data_jp_Command.json",
    [string]$Translation = "scena_data_sc_Command.json",
    [string]$OutputDir = ".",
    [switch]$SkipDownload,
    [switch]$Fresh,
    [int]$NewIdStart = 100000,
    [string]$Uv = "uv"
)

$ErrorActionPreference = "Stop"
$ScriptRoot = $PSScriptRoot

# ---- 输出目录解析（先创建再解析，避免 Resolve-Path 报错）----
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}
$OutputDir = (Resolve-Path $OutputDir).Path

# ---- EVO 侧数据下载源 ----
$ReleaseTag = "v1.1.0"
$BaseUrl = "https://github.com/lxr2010/TrailsInTheSkyRemakeScriptAligner/releases/download/$ReleaseTag"
$scriptDataName = "script_data_$Game.json"
$additionalVoiceName = "additional_voice_$Game.json"
$speakerMapName = "speaker_map_$Game.json"

function Ensure-File([string]$name) {
    $local = Join-Path $OutputDir $name
    if (Test-Path $local) {
        Write-Host "已存在: $local"
        return $local
    }
    if ($SkipDownload) {
        throw "缺少文件 $name，且指定了 -SkipDownload"
    }
    $url = "$BaseUrl/$name"
    Write-Host "下载 $url"
    Invoke-WebRequest -Uri $url -OutFile $local
    Write-Host "  已保存: $local"
    return $local
}

function Ensure-OptionalFile([string]$name) {
    $local = Join-Path $OutputDir $name
    if (Test-Path $local) {
        Write-Host "已存在: $local"
        return $local
    }
    if ($SkipDownload) {
        Write-Host "缺少可选文件 $name，说话人约束将退化为纯文本匹配。"
        return $null
    }
    $url = "$BaseUrl/$name"
    try {
        Write-Host "下载 $url"
        Invoke-WebRequest -Uri $url -OutFile $local
        Write-Host "  已保存: $local"
        return $local
    } catch {
        Write-Host "下载可选文件 $name 失败，说话人约束将退化为纯文本匹配。"
        return $null
    }
}

Write-Host "===== 准备 $Game 的 EVO 侧数据 ====="
$scriptDataPath = Ensure-File $scriptDataName
$additionalVoicePath = Ensure-File $additionalVoiceName
$speakerMapPath = Ensure-OptionalFile $speakerMapName

# ---- Remake 语音表(可选): 来自 SkyStructureAligner Release, 用于 RemakeVoiceFilename 列 ----
$tVoiceName = "t_voice_$Game.json"
$tVoiceLocal = Join-Path $ScriptRoot $tVoiceName
if (-not (Test-Path $tVoiceLocal) -and -not $SkipDownload) {
    $tVoiceUrl = "https://github.com/lxr2010/SkyStructureAligner/releases/download/v1.0.1/$tVoiceName"
    try {
        Write-Host "下载 $tVoiceUrl"
        Invoke-WebRequest -Uri $tVoiceUrl -OutFile $tVoiceLocal
        Write-Host "  已保存: $tVoiceLocal (RemakeVoiceFilename 列可用)"
    } catch {
        Write-Host "下载 $tVoiceName 失败，RemakeVoiceFilename 列将为空。"
    }
}

# ---- Remake 侧数据检查 ----
if (-not (Test-Path $RemakeJp)) {
    throw "未找到 Remake 日文数据: $RemakeJp（请先用 decompile_pac.ps1 生成）"
}
$RemakeJp = (Resolve-Path $RemakeJp).Path
if ($Translation -and (Test-Path $Translation)) {
    $Translation = (Resolve-Path $Translation).Path
} else {
    Write-Host "未找到中文翻译 $Translation，将跳过翻译列。"
    $Translation = ""
}

# ---- 清理共享 LLM 缓存（可选）----
if ($Fresh) {
    Write-Host "清空共享 LLM 缓存..."
    Get-ChildItem $ScriptRoot -Filter "llm_*.json" -File -ErrorAction SilentlyContinue | Remove-Item
}

# ---- 输出文件名按作品区分，避免相互覆盖 ----
$prefix = $Game
$matchesJson = "matches_$prefix.json"
$anchorsJson = "anchors_$prefix.json"
$topKJson = "top_k_matches_$prefix.json"
$unscriptedJson = "unscripted_matches_$prefix.json"
$outputCsv = "match_result_$prefix.csv"
# ---- 构建 main.py 参数 ----
$mainArgs = @(
    "main.py",
    "--remake-jp", $RemakeJp,
    "--script-data", $scriptDataPath,
    "--additional-voice", $additionalVoicePath,
    "--matches-json", $matchesJson,
    "--anchors-json", $anchorsJson,
    "--top-k-json", $topKJson,
    "--unscripted-matches-json", $unscriptedJson,
    "--output-csv", $outputCsv,
    "--new-id-start", $NewIdStart
)
if ($speakerMapPath) {
    $mainArgs += @("--speaker-map", $speakerMapPath)
}
if ($Translation) {
    $mainArgs += @("--translation", $Translation)
}

Write-Host ""
Write-Host "===== 运行 main.py（$Game）====="
Push-Location $ScriptRoot
try {
    & $Uv run python @mainArgs
    if ($LASTEXITCODE -ne 0) { throw "main.py 运行失败（退出码 $LASTEXITCODE）" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "完成。最终匹配表: $(Join-Path $ScriptRoot $outputCsv)"
