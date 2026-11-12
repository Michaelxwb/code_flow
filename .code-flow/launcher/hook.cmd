@echo off
rem code-flow:v1
setlocal
set "ROOT=%~dp0..\.."
set "FORMAT=%~1"
if "%FORMAT%"=="" set "FORMAT=claude"
set "NODE="
where node >nul 2>nul && set "NODE=node"
if not defined NODE set "NODE=/Users/jahan/.nvm/versions/node/v24.17.0/bin/node"
if not exist "%ROOT%\.code-flow\launcher\bridge.cjs" (
  echo code-flow launcher missing; run init again 1>&2
  exit /b 0
)
"%NODE%" "%ROOT%\.code-flow\launcher\bridge.cjs" --format "%FORMAT%" --node "/Users/jahan/.nvm/versions/node/v24.17.0/bin/node" --entry "/Users/jahan/.nvm/versions/node/v24.17.0/lib/node_modules/@michaelxwb/code-flow/bin/code-flow.js"
exit /b 0
