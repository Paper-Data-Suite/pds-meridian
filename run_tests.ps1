param(
    [Parameter(Mandatory = $true)]
    [string]$CoreWheel,
    [switch]$AllowDirty
)

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Error "Expected virtual-environment Python was not found: $python"
    exit 1
}

$arguments = @(
    "scripts/validate_repository.py",
    "--core-wheel",
    $CoreWheel
)
if ($AllowDirty) {
    $arguments += "--allow-dirty"
}

& $python @arguments
exit $LASTEXITCODE
