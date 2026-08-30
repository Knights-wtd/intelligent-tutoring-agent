[CmdletBinding()]
param(
  [string]$Origin = "http://127.0.0.1:8765",
  [string]$Token = $env:AGENT_RUNTIME_TOKEN,
  [ValidateRange(1, 60)]
  [int]$TimeoutSeconds = 10
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Assert-ToolMajor([string]$CommandName, [string]$DisplayName, [int]$ExpectedMajor) {
  $command = Get-Command $CommandName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $command) { throw "$DisplayName $ExpectedMajor is required but was not found on PATH." }
  $versionOutput = @(& $command.Source --version 2>&1)
  $versionExitCode = $LASTEXITCODE
  $version = if ($versionOutput.Count -gt 0) { $versionOutput[0].ToString().Trim() } else { "" }
  if ($versionExitCode -ne 0 -or $version -notmatch '^v?(?<major>\d+)\.' -or [int]$Matches.major -ne $ExpectedMajor) {
    throw "Expected $DisplayName $ExpectedMajor, found $version"
  }
  return $version.TrimStart("v")
}

function Resolve-LoopbackOrigin([string]$Value) {
  try { $uri = [Uri]$Value } catch { throw "Invalid Runtime origin: $Value" }
  if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne "http") {
    throw "Runtime smoke origin must be an absolute http URL."
  }
  if ($uri.Host -notin @("127.0.0.1", "::1", "localhost")) {
    throw "Runtime smoke origin must use a loopback host, found '$($uri.Host)'."
  }
  if ($uri.UserInfo -or $uri.Query -or $uri.Fragment -or ($uri.AbsolutePath -and $uri.AbsolutePath -ne "/")) {
    throw "Runtime smoke origin must not include credentials, a path, query, or fragment."
  }
  return $Value.TrimEnd("/")
}

# Required smoke toolchain: Node.js 24 and pnpm 11.
$nodeVersion = Assert-ToolMajor "node" "Node.js" 24
$pnpmVersion = Assert-ToolMajor "pnpm" "pnpm" 11
$Origin = Resolve-LoopbackOrigin $Origin

$health = Invoke-RestMethod -Uri "$Origin/v1/health" -Method Get -TimeoutSec $TimeoutSeconds
if ($health.status -ne "ok" -or $health.protocol_version -ne "1.0" -or $health.node_version -notmatch '^24\.') {
  throw "Runtime health contract failed."
}

try {
  Invoke-WebRequest -UseBasicParsing -Uri "$Origin/v1/diagnostics" -Method Get -TimeoutSec $TimeoutSeconds | Out-Null
  throw "Diagnostics unexpectedly accepted an unauthenticated request."
} catch {
  $response = $_.Exception.Response
  $statusCode = if ($response) { [int]$response.StatusCode } else { 0 }
  if ($statusCode -ne 401) { throw }
}

if (-not [string]::IsNullOrWhiteSpace($Token)) {
  if ($Token.IndexOfAny(@([char]13, [char]10, [char]0)) -ge 0) {
    throw "Runtime token contains an unsafe control character."
  }
  $diagnostics = Invoke-RestMethod -Uri "$Origin/v1/diagnostics" -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec $TimeoutSeconds
  if ($diagnostics.status -notin @("ok", "degraded")) { throw "Unexpected diagnostics status." }
}

Write-Host "Agent Runtime smoke passed: Node $nodeVersion, pnpm $pnpmVersion, protocol $($health.protocol_version), upstream $($health.upstream_commit)."
