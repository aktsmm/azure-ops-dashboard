param(
  [ValidateSet('onedir','onefile')]
  [string]$Mode = 'onedir'
)

$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

# PyInstaller は開発用ツールなので、プロジェクトの .venv に追加
$python = (Resolve-Path (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')).Path
uv pip install --python $python pyinstaller

# templates/ を exe に同梱（Windows は ; 区切り）
$addData = 'templates;templates'

$buildArgs = @(
  'pyinstaller',
  'main.py',
  '--name', 'AzureOpsDashboard',
  '--noconsole',
  '--clean',
  '--noconfirm',
  '--add-data', $addData
)

if ($Mode -eq 'onefile') {
  $buildArgs += '--onefile'
} else {
  $buildArgs += '--onedir'
}

uv run @buildArgs

Write-Host ''
Write-Host 'Build output:'
Write-Host '  dist\ (配下に exe が生成されます)'
