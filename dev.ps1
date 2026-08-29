param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "info", "run", "debug", "test", "unit", "lint", "all")]
    [string]$Command = "info",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArguments
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $projectRoot "tools\blender_dev.py"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

$python = $null
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $python = $venvPython
    }
}

if (-not $python) {
    $blenderExecutable = $env:BLENDER_EXECUTABLE

    if (-not $blenderExecutable -and $env:ProgramFiles) {
        $blenderExecutable = Get-ChildItem -LiteralPath (Join-Path $env:ProgramFiles "Blender Foundation") `
            -Filter "blender.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }

    if (-not $blenderExecutable -or -not (Test-Path -LiteralPath $blenderExecutable)) {
        throw "Blender was not found. Set BLENDER_EXECUTABLE in the environment or .env file."
    }

    $python = Get-ChildItem -LiteralPath (Split-Path -Parent $blenderExecutable) `
        -Filter "python.exe" -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "[\\/]python[\\/]bin[\\/]python\.exe$" } |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName

    if (-not $python) {
        throw "Blender's bundled Python was not found next to $blenderExecutable."
    }
}

& $python $runner $Command @RunnerArguments
exit $LASTEXITCODE
