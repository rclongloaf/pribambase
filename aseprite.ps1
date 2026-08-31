# Development entry point for the Aseprite extension.
param(
    [Parameter(Position = 0)]
    [ValidateSet("info", "build", "install", "test", "run", "all")]
    [string]$Command = "info",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArguments
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runner = Join-Path $projectRoot "tools\aseprite_dev.py"

if (-not (Test-Path -LiteralPath $python)) {
    throw "The development environment is missing. Run .\dev.ps1 setup first."
}

& $python $runner $Command @RunnerArguments
exit $LASTEXITCODE
