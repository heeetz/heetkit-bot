[CmdletBinding()]
param(
    [string] $PythonPath = ".venv\Scripts\python.exe",
    [string] $InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [string] $PortableZip = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not [IO.Path]::IsPathRooted($PythonPath)) {
    $PythonPath = Join-Path $projectRoot $PythonPath
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Provide a Python interpreter with -PythonPath."
}
$installerArguments = @((Join-Path $PSScriptRoot "build_installer.py"), "--inno-compiler", $InnoCompiler)
if ($PortableZip) { $installerArguments += @("--portable-zip", $PortableZip) }
& $PythonPath @installerArguments
if ($LASTEXITCODE -ne 0) { throw "Installer build failed ($LASTEXITCODE)." }
