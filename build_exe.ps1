param(
  [ValidateSet('onedir','onefile')]
  [string]$Mode = 'onedir',

  [switch]$NoRun,

  # Optional custom dist output root (default: dist)
  [string]$DistPath = 'dist'
)

$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

# If the app is already running, avoid deleting dist output (Windows file lock).
# In that case, build into a timestamped dist folder and skip auto-run.
try {
  $running = Get-Process -Name 'AzureOpsDashboard' -ErrorAction SilentlyContinue
} catch {
  $running = $null
}

$distRoot = $DistPath
if ($running -and $DistPath -eq 'dist') {
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $distRoot = "dist-build-$stamp"
  $NoRun = $true
  Write-Host "INFO: AzureOpsDashboard is running. Building into: $distRoot (auto-run disabled)"
}

# PyInstaller は開発用ツールなので、プロジェクトの .venv に追加
# NOTE: monorepo では親ディレクトリの .venv を優先しつつ、単体リポ構成では同階層 .venv へフォールバック。
$pythonCandidates = @(
  (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
  (Join-Path $PSScriptRoot '.\.venv\Scripts\python.exe')
)

$python = $null
foreach ($cand in $pythonCandidates) {
  if (Test-Path $cand) {
    $python = (Resolve-Path $cand).Path
    break
  }
}

if (-not $python) {
  throw "Python executable not found. Expected one of: `n- $($pythonCandidates -join "`n- ")"
}

# Derive venv root from <venv>\Scripts\python.exe
$venvRoot = Split-Path -Parent (Split-Path -Parent $python)
uv pip install --python $python pyinstaller

# templates/ を exe に同梱（Windows は ; 区切り）
$addData = 'templates;templates'

# Copilot SDK 同梱 CLI バイナリも同梱
$copilotBinDir = Join-Path $venvRoot 'Lib\site-packages\copilot\bin'
if (Test-Path $copilotBinDir) {
  # NOTE: exe 内の top-level "copilot/" は Python SDK モジュール名と衝突し得るため、別名に退避する
  $copilotData = "$copilotBinDir;copilot_cli\bin"
  Write-Host "Copilot CLI binary: $copilotBinDir"
} else {
  $copilotData = $null
  Write-Host "WARNING: Copilot CLI binary not found — AI review will be unavailable in exe"
}

$pyiParams = @(
  '-m', 'PyInstaller',
  'main.py',
  '--name', 'AzureOpsDashboard',
  '--noconsole',
  '--clean',
  '--noconfirm',
  # Avoid overwriting the tracked AzureOpsDashboard.spec in the repo root.
  # (PyInstaller auto-generates a spec file containing absolute paths.)
  '--specpath', (Join-Path $PSScriptRoot 'build\\spec'),
  '--distpath', $distRoot,
  '--add-data', $addData
)

if ($copilotData) {
  $pyiParams += '--add-data'
  $pyiParams += $copilotData
}

if ($Mode -eq 'onefile') {
  $pyiParams += '--onefile'
} else {
  $pyiParams += '--onedir'
}

& $python @pyiParams

Write-Host ''
Write-Host 'Build output:'
Write-Host "  $distRoot\ (配下に exe が生成されます)"

# Build 後に自動起動（既定ON）
if (-not $NoRun) {
  if ($Mode -eq 'onefile') {
    $exePath = Join-Path $PSScriptRoot (Join-Path $distRoot 'AzureOpsDashboard.exe')
  } else {
    $exePath = Join-Path $PSScriptRoot (Join-Path $distRoot 'AzureOpsDashboard\AzureOpsDashboard.exe')
  }

  if (Test-Path $exePath) {
    Write-Host ''
    Write-Host "Launching: $exePath"
    Start-Process -FilePath $exePath | Out-Null
  } else {
    Write-Host "WARNING: exe not found: $exePath"
  }
}
