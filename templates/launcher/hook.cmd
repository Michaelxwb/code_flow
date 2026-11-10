@echo off
rem code-flow:v1
setlocal
set "ROOT=%~dp0..\.."
set "FORMAT=%~1"
if "%FORMAT%"=="" set "FORMAT=claude"
set "NODE="
where node >nul 2>nul && set "NODE=node"
if not defined NODE set "NODE=__FIXED_NODE__"
if not exist "%ROOT%\.code-flow\launcher\bridge.cjs" (
  echo code-flow launcher missing; run init again 1>&2
  exit /b 0
)
"%NODE%" "%ROOT%\.code-flow\launcher\bridge.cjs" --format "%FORMAT%" --node "__FIXED_NODE__" --entry "__FIXED_ENTRY__"
exit /b 0
