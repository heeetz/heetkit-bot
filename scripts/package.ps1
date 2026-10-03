[CmdletBinding()]
param(
    [string] $OutputPath = "twitch-bot-source.zip"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-DistributionExcluded {
    param([Parameter(Mandatory)][string] $RelativePath)

    $path = $RelativePath.Replace("\", "/")
    if ($path -eq ".env.example") {
        return $false
    }
    if ($path -eq ".env" -or $path -like ".env.*") {
        return $true
    }
    if ($path -match "(^|/)(\.git|\.idea|\.vscode|\.venv|venv|env|__pycache__|\.pytest_cache|htmlcov|build|dist)(/|$)") {
        return $true
    }
    if ($path -match "(^|/)[^/]*\.egg-info(/|$)") {
        return $true
    }
    if ($path -match "(?i)(^|/)(\.tio\.tokens|twitchio_tokens|[^/]*tokens?[^/]*)\.json$") {
        return $true
    }
    if ($path -match "(?i)\.(db|sqlite|sqlite3)(-(wal|shm))?$") {
        return $true
    }
    if ($path -match "(?i)(^|/)(\.coverage(?:\..*)?|coverage\.xml|[^/]*\.log|Thumbs\.db|Desktop\.ini|\.DS_Store)$") {
        return $true
    }
    if ($path -match "(?i)\.(py[co]|tmp|temp|bak|orig|rej|patch|diff|zip)$" -or $path.EndsWith("~")) {
        return $true
    }
    if ($path.StartsWith("data/") -and -not $path.StartsWith("data/filters/")) {
        return $true
    }
    return $false
}

$projectRootText = & git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $projectRootText) {
    throw "Run this script from inside the Twitch Bot Git repository."
}

$projectRoot = [IO.Path]::GetFullPath($projectRootText.Trim())
$rootPrefix = $projectRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$resolvedOutput = if ([IO.Path]::IsPathRooted($OutputPath)) {
    [IO.Path]::GetFullPath($OutputPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
}

if (Test-Path -LiteralPath $resolvedOutput) {
    throw "Archive already exists: $resolvedOutput"
}
$outputDirectory = Split-Path -Parent $resolvedOutput
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw "Archive destination directory does not exist: $outputDirectory"
}

$sourceFiles = @(& git -C $projectRoot ls-files --cached)
if ($LASTEXITCODE -ne 0) {
    throw "Could not enumerate tracked source files with Git."
}

$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$stagingDirectory = [IO.Path]::GetFullPath(
    (Join-Path $temporaryRoot ("twitch-bot-package-" + [guid]::NewGuid().ToString("N")))
)
if (-not $stagingDirectory.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to create a staging directory outside the system temporary directory."
}

try {
    New-Item -ItemType Directory -Path $stagingDirectory | Out-Null

    foreach ($relativePath in $sourceFiles) {
        if (Test-DistributionExcluded -RelativePath $relativePath) {
            continue
        }

        $localRelativePath = $relativePath.Replace("/", [IO.Path]::DirectorySeparatorChar)
        $sourcePath = [IO.Path]::GetFullPath((Join-Path $projectRoot $localRelativePath))
        if (-not $sourcePath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to package a path outside the repository: $relativePath"
        }
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Required project file is missing: $relativePath"
        }

        $destinationPath = Join-Path $stagingDirectory $localRelativePath
        $destinationDirectory = Split-Path -Parent $destinationPath
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
    }

    $requiredFiles = @(
        ".env.example",
        ".gitignore",
        "README.md",
        "config.py",
        "pyproject.toml",
        "app/main.py",
        "scripts/package.ps1",
        "tests/test_main.py",
        "data/filters/blocked_words.txt",
        "data/filters/blocked_phrases.txt",
        "data/filters/blocked_patterns.txt"
    )
    foreach ($requiredFile in $requiredFiles) {
        $requiredPath = Join-Path $stagingDirectory $requiredFile
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Distribution is missing required file: $requiredFile"
        }
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory(
        $stagingDirectory,
        $resolvedOutput,
        [IO.Compression.CompressionLevel]::Optimal,
        $false
    )
    $archive = [IO.Compression.ZipFile]::OpenRead($resolvedOutput)
    try {
        $archiveEntries = @(
            $archive.Entries | ForEach-Object { $_.FullName.Replace("\", "/").TrimEnd("/") }
        )
        foreach ($entry in $archive.Entries) {
            $entryPath = $entry.FullName.Replace("\", "/").TrimEnd("/")
            if ($entryPath -and (Test-DistributionExcluded -RelativePath $entryPath)) {
                throw "Unsafe file was included in the archive: $entryPath"
            }
        }
        foreach ($requiredFile in $requiredFiles) {
            if ($archiveEntries -notcontains $requiredFile) {
                throw "Archive is missing required file: $requiredFile"
            }
        }
    } finally {
        $archive.Dispose()
    }

    Write-Host "Created developer source archive (not an application release): $resolvedOutput"
} catch {
    if (Test-Path -LiteralPath $resolvedOutput) {
        Remove-Item -LiteralPath $resolvedOutput -Force
    }
    throw
} finally {
    if (Test-Path -LiteralPath $stagingDirectory) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
}
