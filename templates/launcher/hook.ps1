# code-flow:v1
param([string]$Format = 'claude')
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$bridge = Join-Path $root '.code-flow\launcher\bridge.cjs'
if (-not (Test-Path -LiteralPath $bridge)) {
  [Console]::Error.WriteLine('code-flow launcher missing; run init again')
  exit 0
}
$node = (Get-Command node -ErrorAction SilentlyContinue)
if ($null -eq $node) { $node = '__FIXED_NODE__' } else { $node = $node.Source }
try {
  $text = [Console]::In.ReadToEnd()
  if ([string]::IsNullOrWhiteSpace($text)) { exit 0 }
  $arguments = @($bridge, '--format', $Format, '--node', '__FIXED_NODE__', '--entry', '__FIXED_ENTRY__')
  $start = New-Object System.Diagnostics.ProcessStartInfo
  $start.FileName = $node
  $start.Arguments = '"' + ($arguments -join '" "') + '"'
  $start.WorkingDirectory = $root
  $start.UseShellExecute = $false
  $start.CreateNoWindow = $true
  $start.RedirectStandardInput = $true
  $start.RedirectStandardOutput = $true
  $start.RedirectStandardError = $true
  $start.StandardOutputEncoding = [System.Text.Encoding]::UTF8
  $start.StandardErrorEncoding = [System.Text.Encoding]::UTF8
  $process = [System.Diagnostics.Process]::Start($start)
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
  $process.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
  $process.StandardInput.BaseStream.Flush()
  $process.StandardInput.Close()
  $stdout = $process.StandardOutput.ReadToEnd()
  $stderr = $process.StandardError.ReadToEnd()
  $process.WaitForExit()
  if ($stderr) { [Console]::Error.Write($stderr) }
  if ($process.ExitCode -eq 0 -and $stdout) { $stdout }
} catch {
  [Console]::Error.WriteLine('code-flow launcher failed; run doctor')
}
exit 0
