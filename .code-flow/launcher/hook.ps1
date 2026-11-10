# code-flow:v1
param([string]$Format = 'claude')
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$bridge = Join-Path $root '.code-flow\launcher\bridge.cjs'
if (-not (Test-Path -LiteralPath $bridge)) {
  [Console]::Error.WriteLine('code-flow launcher missing; run init again')
  exit 0
}
$node = (Get-Command node -ErrorAction SilentlyContinue)
if ($null -eq $node) { $node = '/Users/jahan/.nvm/versions/node/v24.17.0/bin/node' } else { $node = $node.Source }
try {
  $text = [Console]::In.ReadToEnd()
  if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }
  $output = $text | & $node $bridge --format $Format --node '/Users/jahan/.nvm/versions/node/v24.17.0/bin/node' --entry '/Users/jahan/workspace/code_flow/bin/code-flow.js'
  if ($LASTEXITCODE -eq 0 -and $output) { $output }
} catch {
  [Console]::Error.WriteLine('code-flow launcher failed; run doctor')
}
exit 0
