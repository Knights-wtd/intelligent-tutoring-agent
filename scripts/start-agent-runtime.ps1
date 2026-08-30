[CmdletBinding()]
param(
  [string]$RepositoryRoot = (Join-Path $PSScriptRoot ".."),
  [string]$EnvironmentFile,
  [ValidateRange(1, 65535)]
  [int]$Port = 8765,
  [ValidateRange(1, 300)]
  [int]$HealthTimeoutSeconds = 30
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Resolve-RepositoryDirectory([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
    throw "Repository root does not exist or is not a directory: $Path"
  }
  return [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
}

function Get-Node24Path {
  $command = Get-Command "node" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $command) { throw "Node.js 24 is required but node was not found on PATH." }
  $versionOutput = @(& $command.Source --version 2>&1)
  $versionExitCode = $LASTEXITCODE
  $version = if ($versionOutput.Count -gt 0) { $versionOutput[0].ToString().Trim() } else { "" }
  if ($versionExitCode -ne 0 -or $version -notmatch '^v?24\.') {
    throw "Agent Runtime requires Node.js 24; found $version"
  }
  return $command.Source
}

function Import-DotEnv([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return }
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Environment file is not a regular file: $Path"
  }
  foreach ($line in Get-Content -LiteralPath $Path) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
    if ($trimmed.StartsWith("export ")) { $trimmed = $trimmed.Substring(7).TrimStart() }
    $parts = $trimmed.Split(@("="), 2, [StringSplitOptions]::None)
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
    if ($value.Length -ge 2) {
      $first = $value[0]
      $last = $value[$value.Length - 1]
      if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
        $value = $value.Substring(1, $value.Length - 2)
      }
    }
    if ($null -eq [Environment]::GetEnvironmentVariable($name, "Process")) {
      [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
  }
}

function Assert-RequiredSecret([string]$Value, [string]$Name) {
  if ([string]::IsNullOrWhiteSpace($Value)) {
    throw "$Name must be set in the process environment or an ignored .env file."
  }
  if ($Value.IndexOfAny(@([char]13, [char]10, [char]0)) -ge 0) {
    throw "$Name contains an unsafe control character."
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

function Resolve-ManagedPath([string]$ConfiguredPath, [string]$RepositoryRoot, [string]$ManagedRoot, [string]$Description) {
  $candidate = if ([IO.Path]::IsPathRooted($ConfiguredPath)) {
    [IO.Path]::GetFullPath($ConfiguredPath)
  } else {
    [IO.Path]::GetFullPath((Join-Path $RepositoryRoot $ConfiguredPath))
  }
  $root = [IO.Path]::GetFullPath($ManagedRoot).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
  $rootPrefix = $root + [IO.Path]::DirectorySeparatorChar
  if (-not $candidate.Equals($root, [StringComparison]::OrdinalIgnoreCase) -and
      -not $candidate.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "$Description resolves outside the managed data root '$root'; refusing unsafe path '$candidate'."
  }
  Assert-NotReparsePoint $root "Managed Agent data root"
  $probe = $candidate
  while ($probe.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or $probe.Equals($root, [StringComparison]::OrdinalIgnoreCase)) {
    Assert-NotReparsePoint $probe $Description
    if ($probe.Equals($root, [StringComparison]::OrdinalIgnoreCase)) { break }
    $probe = [IO.Path]::GetDirectoryName($probe)
  }
  return $candidate
}

function Test-HealthyRuntime([string]$Origin) {
  try {
    $health = Invoke-RestMethod -Uri "$Origin/v1/health" -Method Get -TimeoutSec 2
    return ($health.status -eq "ok" -and $health.protocol_version -eq "1.0" -and $health.node_version -match '^24\.')
  } catch {
    return $false
  }
}

function Test-ExpectedRuntimeProcess([int]$ProcessId, [string]$RuntimeEntry) {
  try {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
    if (-not $processInfo) { return $false }
    return $processInfo.CommandLine -and $processInfo.CommandLine.IndexOf($RuntimeEntry, [StringComparison]::OrdinalIgnoreCase) -ge 0
  } catch {
    return $false
  }
}

function Write-AtomicText([string]$Path, [string]$Content) {
  $temporary = "$Path.$PID.tmp"
  [IO.File]::WriteAllText($temporary, $Content, [Text.UTF8Encoding]::new($false))
  Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Start-ProcessWithoutInheritedConsolePipes(
  [hashtable]$StartProcessParameters,
  [scriptblock]$StartProcessInvoker,
  [scriptblock]$GetStandardHandle,
  [scriptblock]$GetHandleFlags,
  [scriptblock]$SetHandleInheritance,
  [scriptblock]$KillProcessTree,
  [scriptblock]$TaskKillInvoker
) {
  if (-not ("AgentRuntime.NativeMethods" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace AgentRuntime {
  public static class NativeMethods {
    public const uint HANDLE_FLAG_INHERIT = 0x00000001;

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetHandleInformation(IntPtr hObject, out uint lpdwFlags);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetHandleInformation(IntPtr hObject, uint dwMask, uint dwFlags);
  }
}
"@
  }

  if (-not $StartProcessInvoker) {
    $StartProcessInvoker = {
      param([hashtable]$Parameters)
      Start-Process @Parameters
    }
  }
  if (-not $GetStandardHandle) {
    $GetStandardHandle = {
      param([int]$StandardHandleId)
      [AgentRuntime.NativeMethods]::GetStdHandle($StandardHandleId)
    }
  }
  if (-not $GetHandleFlags) {
    $GetHandleFlags = {
      param([IntPtr]$Handle)
      [uint32]$flags = 0
      if (-not [AgentRuntime.NativeMethods]::GetHandleInformation($Handle, [ref]$flags)) {
        throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
      }
      return $flags
    }
  }
  if (-not $SetHandleInheritance) {
    $SetHandleInheritance = {
      param([IntPtr]$Handle, [bool]$Inheritable)
      $inheritFlag = if ($Inheritable) { [AgentRuntime.NativeMethods]::HANDLE_FLAG_INHERIT } else { 0 }
      if (-not [AgentRuntime.NativeMethods]::SetHandleInformation(
        $Handle,
        [AgentRuntime.NativeMethods]::HANDLE_FLAG_INHERIT,
        $inheritFlag
      )) {
        throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
      }
    }
  }
  if (-not $KillProcessTree) {
    $KillProcessTree = {
      param([Diagnostics.Process]$Process)
      $Process.Kill($true)
    }
  }
  if (-not $TaskKillInvoker) {
    $TaskKillInvoker = {
      param([string]$FilePath, [string[]]$ArgumentList, [int]$TimeoutMilliseconds)

      $startInfo = [Diagnostics.ProcessStartInfo]::new()
      $startInfo.FileName = $FilePath
      $startInfo.UseShellExecute = $false
      $startInfo.CreateNoWindow = $true
      $startInfo.RedirectStandardOutput = $true
      $startInfo.RedirectStandardError = $true
      foreach ($argument in $ArgumentList) {
        $startInfo.ArgumentList.Add($argument)
      }

      $taskKillProcess = [Diagnostics.Process]::new()
      $taskKillProcess.StartInfo = $startInfo
      try {
        if (-not $taskKillProcess.Start()) {
          throw [InvalidOperationException]::new("Windows process-tree cleanup utility did not start.")
        }
        $standardOutputTask = $taskKillProcess.StandardOutput.ReadToEndAsync()
        $standardErrorTask = $taskKillProcess.StandardError.ReadToEndAsync()
        if (-not $taskKillProcess.WaitForExit($TimeoutMilliseconds)) {
          try {
            $taskKillProcess.Kill($true)
            $taskKillProcess.WaitForExit(1000) | Out-Null
          } catch {
            # Cleanup confirmation remains false regardless of whether the timed
            # out utility itself can be stopped.
          }
          return [pscustomobject]@{
            Completed = $false
            ExitCode = $null
          }
        }
        $standardOutputTask.GetAwaiter().GetResult() | Out-Null
        $standardErrorTask.GetAwaiter().GetResult() | Out-Null
        return [pscustomobject]@{
          Completed = $true
          ExitCode = [int]$taskKillProcess.ExitCode
        }
      } finally {
        $taskKillProcess.Dispose()
      }
    }
  }

  # Start-Process redirects the child's standard streams, but on Windows it can
  # still inherit the calling automation's console/pipe handles as extra open
  # handles. A long-running Runtime then keeps those pipes alive after this
  # PowerShell process exits, so callers waiting for pipe EOF hang indefinitely.
  # Temporarily clearing HANDLE_FLAG_INHERIT prevents that leak while preserving
  # the explicit file redirects below. Every changed handle is restored on a
  # best-effort basis; a child is returned only after all restorations succeed.
  $changedHandles = [Collections.Generic.List[object]]::new()
  $restorationErrors = [Collections.Generic.List[object]]::new()
  $childProcess = $null
  $operationError = $null
  try {
    foreach ($standardHandleId in @(-10, -11, -12)) {
      $handle = & $GetStandardHandle $standardHandleId
      if ($handle -eq [IntPtr]::Zero -or $handle -eq [IntPtr]::new(-1)) { continue }

      [uint32]$flags = & $GetHandleFlags $handle
      if (($flags -band [AgentRuntime.NativeMethods]::HANDLE_FLAG_INHERIT) -eq 0) { continue }

      & $SetHandleInheritance $handle $false | Out-Null
      $changedHandles.Add($handle)
    }

    $childProcess = & $StartProcessInvoker $StartProcessParameters
  } catch {
    $operationError = $_
  } finally {
    foreach ($handle in $changedHandles) {
      try {
        & $SetHandleInheritance $handle $true | Out-Null
      } catch {
        $restorationErrors.Add($_)
      }
    }
  }

  if ($restorationErrors.Count -gt 0) {
    if ($childProcess) {
      $cleanupConfirmed = $false
      try {
        $rootProcessId = [int]$childProcess.Id
        if ($rootProcessId -le 0) {
          throw [InvalidOperationException]::new("Started Runtime process did not expose a valid process identifier.")
        }

        # Start-Process -PassThru supplies the authoritative root Process. Force
        # its native handle open before checking liveness; keeping that handle
        # alive pins the Windows process object and prevents this PID from being
        # reused while fallback cleanup is in progress.
        $rootProcessHandle = $childProcess.Handle
        if ($rootProcessHandle -eq [IntPtr]::Zero -or $rootProcessHandle -eq [IntPtr]::new(-1)) {
          throw [InvalidOperationException]::new("Started Runtime process did not expose a stable process handle.")
        }

        $childProcess.Refresh()
        if ($childProcess.HasExited) {
          throw [InvalidOperationException]::new("The Runtime root exited before process-tree cleanup could be confirmed.")
        }

        $primaryTreeKillSucceeded = $false
        try {
          & $KillProcessTree $childProcess | Out-Null
          $primaryTreeKillSucceeded = $true
        } catch {
          # Fall back only while the same stable root Process is still alive.
          # We deliberately do not enumerate or terminate descendant PIDs: a CIM
          # snapshot cannot prove completeness and PID reuse can target an
          # unrelated process.
          $childProcess.Refresh()
          if ($childProcess.HasExited) {
            throw [InvalidOperationException]::new("The Runtime root exited before fallback cleanup could be confirmed.")
          }

          $systemDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::System)
          $taskKillPath = Join-Path $systemDirectory "taskkill.exe"
          if (-not (Test-Path -LiteralPath $taskKillPath -PathType Leaf)) {
            throw [InvalidOperationException]::new("Windows process-tree cleanup utility is unavailable.")
          }

          # Invoke the controlled absolute utility directly with a fixed argument
          # array. No cmd.exe, string-built command, user input, or secrets are
          # included. A successful exit is necessary but not sufficient: the
          # stable root Process must also be observed exited below.
          $taskKillArguments = @("/PID", [string]$rootProcessId, "/T", "/F")
          $taskKillResult = & $TaskKillInvoker $taskKillPath $taskKillArguments 10000
          if ($null -eq $taskKillResult -or
              -not $taskKillResult.Completed -or
              [int]$taskKillResult.ExitCode -ne 0) {
            throw [InvalidOperationException]::new("Windows process-tree cleanup utility did not complete successfully.")
          }

          if (-not $childProcess.WaitForExit(10000)) {
            throw [InvalidOperationException]::new("The Runtime root did not exit after fallback cleanup.")
          }
          $childProcess.Refresh()
          if (-not $childProcess.HasExited) {
            throw [InvalidOperationException]::new("The Runtime root exit could not be confirmed after fallback cleanup.")
          }
          $cleanupConfirmed = $true
        }

        if ($primaryTreeKillSucceeded) {
          if (-not $childProcess.WaitForExit(10000)) {
            throw [InvalidOperationException]::new("The Runtime root did not exit after process-tree cleanup.")
          }
          $childProcess.Refresh()
          if (-not $childProcess.HasExited) {
            throw [InvalidOperationException]::new("The Runtime root exit could not be confirmed after process-tree cleanup.")
          }
          $cleanupConfirmed = $true
        }
      } catch {
        $cleanupConfirmed = $false
      }

      if (-not $cleanupConfirmed) {
        throw [InvalidOperationException]::new(
          "Agent Runtime launch failed because inherited standard handles could not be restored, and cleanup of the started process tree could not be confirmed."
        )
      }
      throw [InvalidOperationException]::new(
        "Agent Runtime launch failed because inherited standard handles could not be restored; the started process tree was terminated."
      )
    }

    throw [InvalidOperationException]::new(
      "Agent Runtime launch failed because inherited standard handles could not be restored."
    )
  }

  if ($operationError) {
    throw $operationError
  }
  if (-not $childProcess) {
    throw [InvalidOperationException]::new("Agent Runtime launch did not return a process handle.")
  }
  return $childProcess
}

$RepositoryRoot = Resolve-RepositoryDirectory $RepositoryRoot
if ([string]::IsNullOrWhiteSpace($EnvironmentFile)) {
  $EnvironmentFile = Join-Path $RepositoryRoot ".env"
} else {
  $EnvironmentFile = [IO.Path]::GetFullPath($EnvironmentFile)
}
Import-DotEnv $EnvironmentFile
Assert-RequiredSecret $env:AGENT_RUNTIME_TOKEN "AGENT_RUNTIME_TOKEN"
Assert-RequiredSecret $env:AGENT_CAPABILITY_SECRET "AGENT_CAPABILITY_SECRET"

$nodePath = Get-Node24Path
$runtimeDir = Join-Path $RepositoryRoot "apps\agent-runtime"
$runtimeEntry = Join-Path $runtimeDir "dist\index.js"
if (-not (Test-Path -LiteralPath $runtimeEntry -PathType Leaf)) {
  throw "Agent Runtime is not built. Expected entry point: $runtimeEntry"
}

$dataRoot = Join-Path $RepositoryRoot ".agent-data"
Assert-NotReparsePoint $dataRoot "Managed Agent data root"
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
Assert-NotReparsePoint $dataRoot "Managed Agent data root"
$stateRoot = Resolve-ManagedPath ".agent-data/runtime-state" $RepositoryRoot $dataRoot "Runtime state path"
$logRoot = Resolve-ManagedPath ".agent-data/logs" $RepositoryRoot $dataRoot "Runtime log path"
$vaultRoot = Resolve-ManagedPath ".agent-data/vault" $RepositoryRoot $dataRoot "Runtime vault path"
$sidecarConfigured = if ($env:AGENT_SIDECAR_ROOT) { $env:AGENT_SIDECAR_ROOT } else { ".agent-data/sidecars" }
$sidecarRoot = Resolve-ManagedPath $sidecarConfigured $RepositoryRoot $dataRoot "Runtime sidecar path"
New-Item -ItemType Directory -Force -Path $stateRoot, $logRoot, $vaultRoot, $sidecarRoot | Out-Null
Assert-NotReparsePoint $stateRoot "Runtime state path"
Assert-NotReparsePoint $logRoot "Runtime log path"
Assert-NotReparsePoint $sidecarRoot "Runtime sidecar path"

$origin = "http://127.0.0.1:$Port"
$env:AGENT_RUNTIME_HOST = "127.0.0.1"
$env:AGENT_RUNTIME_PORT = [string]$Port
$env:AGENT_RUNTIME_SIDECAR_ROOT = $sidecarRoot
$env:AGENT_RUNTIME_VAULT_ROOT = $vaultRoot
$pnpmStore = Join-Path $RepositoryRoot "node_modules\.pnpm"
$nativePackage = if (Test-Path -LiteralPath $pnpmStore -PathType Container) {
  Get-ChildItem -LiteralPath $pnpmStore -Directory -Filter "@anthropic-ai+claude-agent-sdk-win32-x64@*" | Select-Object -First 1
} else {
  $null
}
if ($nativePackage) {
  $nativeExecutable = Join-Path $nativePackage.FullName "node_modules\@anthropic-ai\claude-agent-sdk-win32-x64\claude.exe"
  if (Test-Path -LiteralPath $nativeExecutable -PathType Leaf) {
    $env:AGENT_RUNTIME_CLAUDE_EXECUTABLE = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $nativeExecutable).Path)
  }
}
$env:AGENT_RUNTIME_SESSION_STATE = Join-Path $stateRoot "sessions.json"
$env:AGENT_RUNTIME_CAPABILITY_SECRET = $env:AGENT_CAPABILITY_SECRET
$env:AGENT_RUNTIME_MAX_CONTEXT_TOKENS = if ($env:AGENT_CONTEXT_WINDOW) { $env:AGENT_CONTEXT_WINDOW } else { "1000000" }
$env:AGENT_RUNTIME_INLINE_EVENT_BYTES = if ($env:AGENT_INLINE_EVENT_BYTES) { $env:AGENT_INLINE_EVENT_BYTES } else { "262144" }

$pidFile = Join-Path $stateRoot "runtime.pid"
$metadataFile = Join-Path $stateRoot "runtime.json"
if (Test-Path -LiteralPath $pidFile) {
  $pidText = (Get-Content -Raw -LiteralPath $pidFile).Trim()
  $existingPid = 0
  if ([int]::TryParse($pidText, [ref]$existingPid) -and $existingPid -gt 0) {
    $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($existingProcess) {
      if (Test-ExpectedRuntimeProcess $existingPid $runtimeEntry) {
        if (Test-HealthyRuntime $origin) {
          Write-Host "Agent Runtime is already healthy on $origin (PID $existingPid)."
          exit 0
        }
        throw "Agent Runtime PID $existingPid exists but is not healthy on $origin; refusing to start a duplicate."
      }
    }
  }
  Remove-Item -LiteralPath $pidFile -Force
  if (Test-Path -LiteralPath $metadataFile) { Remove-Item -LiteralPath $metadataFile -Force }
}

if (Test-HealthyRuntime $origin) {
  throw "A Runtime is already listening on $origin but is not managed by this PID file; refusing to adopt it."
}

$stdout = Join-Path $logRoot "agent-runtime.stdout.log"
$stderr = Join-Path $logRoot "agent-runtime.stderr.log"
$stdin = Join-Path $stateRoot "runtime.stdin"
[IO.File]::WriteAllText($stdin, "", [Text.UTF8Encoding]::new($false))
$quotedEntry = '"' + $runtimeEntry + '"'
$process = $null
try {
  # Secrets are inherited through the process environment. They are intentionally absent from ArgumentList.
  $process = Start-ProcessWithoutInheritedConsolePipes @{
    FilePath = $nodePath
    ArgumentList = @($quotedEntry)
    WorkingDirectory = $runtimeDir
    WindowStyle = "Hidden"
    PassThru = $true
    RedirectStandardInput = $stdin
    RedirectStandardOutput = $stdout
    RedirectStandardError = $stderr
  }

  Write-AtomicText $pidFile ([string]$process.Id)
  $metadata = [ordered]@{
    pid = $process.Id
    started_at_utc = [DateTime]::UtcNow.ToString("o")
    executable = $nodePath
    entry_point = $runtimeEntry
    origin = $origin
    stdout_log = $stdout
    stderr_log = $stderr
  } | ConvertTo-Json -Depth 3
  Write-AtomicText $metadataFile $metadata

  $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
  do {
    $process.Refresh()
    if ($process.HasExited) {
      throw "Agent Runtime exited before becoming healthy (exit code $($process.ExitCode)); inspect $stderr"
    }
    if (Test-HealthyRuntime $origin) {
      Write-Host "Agent Runtime started and is healthy on $origin (PID $($process.Id))."
      exit 0
    }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $deadline)

  throw "Agent Runtime did not become healthy within $HealthTimeoutSeconds seconds; inspect $stderr"
} catch {
  if ($process) {
    $process.Refresh()
    if (-not $process.HasExited) {
      Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
  }
  if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile -Force }
  if (Test-Path -LiteralPath $metadataFile) { Remove-Item -LiteralPath $metadataFile -Force }
  throw
}
