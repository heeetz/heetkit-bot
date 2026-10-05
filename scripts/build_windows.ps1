[CmdletBinding()]
param([string] $PythonPath = ".venv\Scripts\python.exe")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not [IO.Path]::IsPathRooted($PythonPath)) {
    $PythonPath = Join-Path $projectRoot $PythonPath
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Provide a Windows x64 Python 3.14.7 interpreter with -PythonPath."
}
& $PythonPath (Join-Path $PSScriptRoot "build_windows.py")
if ($LASTEXITCODE -ne 0) { throw "Windows build failed ($LASTEXITCODE)." }
