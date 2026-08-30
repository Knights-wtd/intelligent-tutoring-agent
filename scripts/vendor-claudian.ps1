[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$SourceRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExpectedRepository = 'https://github.com/YishenTu/claudian'
$ExpectedVersion = '2.2.4'
$ExpectedCommit = 'd190786d11cc0b067475dcffbf8c334ee565d208'
$ExpectedArchiveFileCount = 1569
$ExpectedArchiveTreeSha256 = 'abc305a71cdf700b7b7721aae0dd9d9c5bface24d6b5d40f24c993ab869933c8'
$VendorDate = '2026-08-28'
$Include = @(
  'src/core/execution',
  'src/core/providers',
  'src/core/tools',
  'src/core/security',
  'src/core/prompt',
  'src/core/skills',
  'src/core/process',
  'src/core/storage/VaultFileAdapter.ts',
  'src/providers/claude/execution',
  'src/providers/claude/history',
  'src/providers/claude/runtime',
  'src/providers/claude/security',
  'src/providers/claude/storage'
)

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$PathComparer = [System.StringComparer]::OrdinalIgnoreCase

function Write-StableUtf8File {
  param(
    [Parameter(Mandatory = $true)][string]$LiteralPath,
    [Parameter(Mandatory = $true)][string]$Content
  )

  $normalized = $Content -replace "`r`n", "`n" -replace "`r", "`n"
  [System.IO.File]::WriteAllText($LiteralPath, $normalized, $Utf8NoBom)
}

function Get-NormalizedRelativePath {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Path
  )

  $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
  $fullPath = [System.IO.Path]::GetFullPath($Path)
  $rootPrefix = $fullRoot + [System.IO.Path]::DirectorySeparatorChar
  if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Path '$fullPath' is outside source root '$fullRoot'."
  }

  return $fullPath.Substring($rootPrefix.Length).Replace('\', '/')
}

function Sort-NormalizedPaths {
  param([Parameter(Mandatory = $true)][string[]]$Paths)

  $items = [System.Collections.Generic.List[string]]::new()
  $items.AddRange($Paths)
  $comparison = [System.Comparison[string]]{
    param([string]$left, [string]$right)
    [System.String]::CompareOrdinal($left.ToLowerInvariant(), $right.ToLowerInvariant())
  }
  $items.Sort($comparison)
  return $items.ToArray()
}

function Get-Sha256Hex {
  param([Parameter(Mandatory = $true)][string]$LiteralPath)

  return (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-StringSha256Hex {
  param([Parameter(Mandatory = $true)][string]$Content)

  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = $Utf8NoBom.GetBytes($Content)
    return ([System.BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
  }
  finally {
    $sha256.Dispose()
  }
}

function Assert-ApprovedSource {
  param([Parameter(Mandatory = $true)][string]$Root)

  $gitMarker = Join-Path $Root '.git'
  if (Test-Path -LiteralPath $gitMarker) {
    $actualCommit = (& git -C $Root rev-parse HEAD 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($actualCommit)) {
      throw "Could not read the Claudian git commit from '$Root'."
    }
    if ($actualCommit -ne $ExpectedCommit) {
      throw "Expected Claudian commit $ExpectedCommit, got $actualCommit."
    }
    return
  }

  $packagePath = Join-Path $Root 'package.json'
  if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
    throw "The no-.git source archive is missing package.json: '$packagePath'."
  }

  $package = Get-Content -LiteralPath $packagePath -Raw | ConvertFrom-Json
  if ($package.version -ne $ExpectedVersion) {
    throw "Expected Claudian archive version $ExpectedVersion, got $($package.version)."
  }

  $archiveFiles = @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force)
  if ($archiveFiles.Count -ne $ExpectedArchiveFileCount) {
    throw "Expected approved Claudian archive with $ExpectedArchiveFileCount files, got $($archiveFiles.Count)."
  }

  $relativePaths = [string[]]($archiveFiles | ForEach-Object {
    Get-NormalizedRelativePath -Root $Root -Path $_.FullName
  })
  $relativePaths = Sort-NormalizedPaths -Paths $relativePaths

  $treeLines = foreach ($relativePath in $relativePaths) {
    $sourcePath = Join-Path $Root ($relativePath.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
    "$(Get-Sha256Hex -LiteralPath $sourcePath)  $relativePath"
  }
  $treeManifest = ($treeLines -join "`n") + "`n"
  $actualTreeSha256 = Get-StringSha256Hex -Content $treeManifest
  if ($actualTreeSha256 -ne $ExpectedArchiveTreeSha256) {
    throw "Expected approved Claudian archive tree SHA-256 $ExpectedArchiveTreeSha256, got $actualTreeSha256."
  }
}

$resolvedSourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot 'apps/agent-runtime'))
$vendorRoot = [System.IO.Path]::GetFullPath((Join-Path $runtimeRoot 'src/claudian'))
$expectedVendorPrefix = [System.IO.Path]::GetFullPath((Join-Path $runtimeRoot 'src')) + [System.IO.Path]::DirectorySeparatorChar
if (-not $vendorRoot.StartsWith($expectedVendorPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing to write outside the agent runtime source directory: '$vendorRoot'."
}

Assert-ApprovedSource -Root $resolvedSourceRoot

$selected = [System.Collections.Generic.Dictionary[string, string]]::new($PathComparer)
foreach ($relativeInclude in $Include) {
  $sourcePath = Join-Path $resolvedSourceRoot ($relativeInclude.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
  if (-not (Test-Path -LiteralPath $sourcePath)) {
    throw "Required Claudian source path is missing: '$relativeInclude'."
  }

  $item = Get-Item -LiteralPath $sourcePath
  $files = if ($item.PSIsContainer) {
    Get-ChildItem -LiteralPath $sourcePath -Recurse -File
  }
  else {
    @($item)
  }

  foreach ($file in $files) {
    $relativePath = Get-NormalizedRelativePath -Root $resolvedSourceRoot -Path $file.FullName
    $selected[$relativePath] = $file.FullName
  }
}

$selectedPaths = [string[]]$selected.Keys
$selectedPaths = Sort-NormalizedPaths -Paths $selectedPaths
if ($selectedPaths.Count -eq 0) {
  throw 'The Claudian include list selected no files.'
}
if ($selectedPaths | Where-Object { $_ -match '(^|/)main\.ts$' -or $_ -like 'src/features/*' }) {
  throw 'The Claudian include list unexpectedly selected an Obsidian UI entry point.'
}

if (Test-Path -LiteralPath $vendorRoot) {
  Remove-Item -LiteralPath $vendorRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $vendorRoot -Force | Out-Null

$manifestFiles = foreach ($relativePath in $selectedPaths) {
  $destinationPath = Join-Path $vendorRoot ($relativePath.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
  $destinationDirectory = Split-Path -Parent $destinationPath
  New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
  Copy-Item -LiteralPath $selected[$relativePath] -Destination $destinationPath

  [ordered]@{
    path = $relativePath
    sha256 = Get-Sha256Hex -LiteralPath $destinationPath
  }
}

$manifest = [ordered]@{
  schemaVersion = 1
  upstreamRepository = $ExpectedRepository
  upstreamVersion = $ExpectedVersion
  upstreamCommit = $ExpectedCommit
  upstreamTreeSha256 = $ExpectedArchiveTreeSha256
  vendorDate = $VendorDate
  files = @($manifestFiles)
}
$manifestJson = ($manifest | ConvertTo-Json -Depth 5) + "`n"
Write-StableUtf8File -LiteralPath (Join-Path $runtimeRoot 'FILES.json') -Content $manifestJson

$includeList = ($Include | ForEach-Object { "- ``$_``" }) -join "`n"
$upstreamDocument = @"
# Claudian upstream source

- Repository: $ExpectedRepository
- Version: $ExpectedVersion
- Approved commit: ``$ExpectedCommit``
- Approved archive tree SHA-256: ``$ExpectedArchiveTreeSha256``
- Vendor date: $VendorDate
- License: MIT; see ``licenses/claudian-MIT.txt``

The vendoring script accepts either a Git checkout exactly at the approved commit or the approved no-``.git`` source archive. Archive approval requires both package version $ExpectedVersion and the full $ExpectedArchiveFileCount-file tree digest above.

## Copied scope

$includeList

Files are copied byte-for-byte beneath ``src/claudian/<original-path>``. The Obsidian plugin UI entry point and ``src/features`` UI tree are intentionally excluded.
"@
Write-StableUtf8File -LiteralPath (Join-Path $runtimeRoot 'UPSTREAM.md') -Content ($upstreamDocument.TrimEnd() + "`n")

$patchesDocument = @"
# Claudian downstream patches

The mirrored files listed in ``FILES.json`` are copied byte-for-byte from Claudian $ExpectedVersion. No patch is applied inside ``src/claudian`` during vendoring; every listed hash therefore describes the copied upstream bytes.

The runtime integration layer must keep the following downstream adaptations outside the mirrored tree, or record any future edits here before regenerating ``FILES.json``:

1. **Import redirection** - host-facing imports are redirected through agent-runtime adapters instead of importing the Obsidian plugin entry point.
2. **Obsidian boundary replacement** - Vault, workspace, notice, and UI dependencies are replaced by explicit host interfaces; no React or Obsidian settings component reads attribution files.
3. **Node host adaptation** - process lifecycle, filesystem paths, environment access, and stream cleanup are supplied by the Node 24 runtime host.
4. **Security patches** - permission updates, path containment, command execution, and persisted session data remain behind the runtime capability and authorization boundaries.

Conformance tests under ``tests/conformance`` preserve selected upstream behavioral intent while avoiding UI-only dependencies. Adapter-specific differences are asserted there rather than hidden in the mirrored source.
"@
Write-StableUtf8File -LiteralPath (Join-Path $runtimeRoot 'PATCHES.md') -Content ($patchesDocument.TrimEnd() + "`n")

$noticeDocument = @"
# Third-party notices

This distribution contains selected source files from **Claudian $ExpectedVersion** ($ExpectedRepository), pinned to commit ``$ExpectedCommit``.

Claudian is licensed under the MIT License. The complete license text is distributed at ``licenses/claudian-MIT.txt`` and must remain with source and binary distributions that include the vendored code.

Attribution files are packaging artifacts and are not loaded or displayed by React or Obsidian settings components.
"@
Write-StableUtf8File -LiteralPath (Join-Path $runtimeRoot 'THIRD_PARTY_NOTICES.md') -Content ($noticeDocument.TrimEnd() + "`n")

$licenseDirectory = Join-Path $runtimeRoot 'licenses'
New-Item -ItemType Directory -Path $licenseDirectory -Force | Out-Null
$licenseText = Get-Content -LiteralPath (Join-Path $resolvedSourceRoot 'LICENSE') -Raw
Write-StableUtf8File -LiteralPath (Join-Path $licenseDirectory 'claudian-MIT.txt') -Content (($licenseText -replace "`r`n", "`n" -replace "`r", "`n").TrimEnd() + "`n")

Write-Host "Vendored $($selectedPaths.Count) Claudian files from $ExpectedCommit."
