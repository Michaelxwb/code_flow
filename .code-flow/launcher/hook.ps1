# code-flow:v1
param([string]$Format = 'claude')
$cmd = Join-Path $PSScriptRoot 'hook.cmd'
if (-not (Test-Path -LiteralPath $cmd)) {
  [Console]::Error.WriteLine('code-flow launcher missing; run init again')
  exit 0
}
$shell = if ($env:ComSpec) { $env:ComSpec } else { 'cmd.exe' }
& $shell /d /c call $cmd $Format
exit 0
