[CmdletBinding()]
param(
  [string]$RepositoryRoot = (Join-Path $PSScriptRoot ".."),
  [switch]$SkipStartupRegistration
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Resolve-RepositoryDirectory([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
    throw "Repository root does not exist or is not a directory: $Path"
  }
  return [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
}

function Get-RequiredToolVersion([string]$CommandName, [string]$DisplayName) {
  $command = Get-Command $CommandName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $command) {
    throw "$DisplayName is required but was not found on PATH."
  }
  $versionOutput = @(& $command.Source --version 2>&1)
  $versionExitCode = $LASTEXITCODE
  $version = if ($versionOutput.Count -gt 0) { $versionOutput[0].ToString().Trim() } else { "" }
  if ($versionExitCode -ne 0 -or -not $version) {
    throw "Unable to determine $DisplayName version using '$($command.Source) --version'."
  }
  return @{ Path = $command.Source; Version = $version }
}

function Assert-MajorVersion([string]$Version, [int]$ExpectedMajor, [string]$DisplayName) {
  if ($Version -notmatch '^v?(?<major>\d+)\.') {
    throw "Unable to parse $DisplayName version: $Version"
  }
  if ([int]$Matches.major -ne $ExpectedMajor) {
    throw "Agent Runtime requires $DisplayName $ExpectedMajor; found $Version"
  }
}

function Assert-NotReparsePoint([string]$Path, [string]$Description) {
  if (Test-Path -LiteralPath $Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "$Description must not be a symbolic link or junction: $Path"
    }
  }
}

$RepositoryRoot = Resolve-RepositoryDirectory $RepositoryRoot
$runtimeDir = Join-Path $RepositoryRoot "apps\agent-runtime"
$runtimePackage = Join-Path $runtimeDir "package.json"
$startScript = Join-Path $RepositoryRoot "scripts\start-agent-runtime.ps1"
if (-not (Test-Path -LiteralPath $runtimePackage -PathType Leaf)) {
  throw "Agent Runtime package is missing: $runtimePackage"
}
if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
  throw "Agent Runtime start script is missing: $startScript"
}

# Required toolchain: Node.js 24 and pnpm 11.
$node = Get-RequiredToolVersion "node" "Node.js"
Assert-MajorVersion $node.Version 24 "Node.js"
$pnpm = Get-RequiredToolVersion "pnpm" "pnpm"
Assert-MajorVersion $pnpm.Version 11 "pnpm"

& $pnpm.Path --dir $runtimeDir install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw "pnpm install failed with exit code $LASTEXITCODE" }
& $pnpm.Path --dir $runtimeDir build
if ($LASTEXITCODE -ne 0) { throw "Agent Runtime build failed with exit code $LASTEXITCODE" }

$runtimeEntry = Join-Path $runtimeDir "dist\index.js"
if (-not (Test-Path -LiteralPath $runtimeEntry -PathType Leaf)) {
  throw "Agent Runtime build did not produce the expected entry point: $runtimeEntry"
}

$dataRoot = Join-Path $RepositoryRoot ".agent-data"
Assert-NotReparsePoint $dataRoot "Managed Agent data root"
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
Assert-NotReparsePoint $dataRoot "Managed Agent data root"
@("vault", "sidecars", "runtime-state", "logs") | ForEach-Object {
  $directory = Join-Path $dataRoot $_
  Assert-NotReparsePoint $directory "Managed Agent data directory"
  New-Item -ItemType Directory -Force -Path $directory | Out-Null
  Assert-NotReparsePoint $directory "Managed Agent data directory"
}

if (-not $SkipStartupRegistration) {
  $startup = [Environment]::GetFolderPath("Startup")
  if (-not $startup) { throw "Unable to resolve the current-user Startup directory." }
  $launcher = Join-Path $startup "TextbookAgentRuntime.cmd"
  $content = "@echo off`r`npowershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`"`r`n"
  [IO.File]::WriteAllText($launcher, $content, [Text.UTF8Encoding]::new($false))
  Write-Host "Registered current-user startup launcher: $launcher"
}

Write-Host "Agent Runtime installed for Node $($node.Version.TrimStart('v')) / pnpm $($pnpm.Version)."
