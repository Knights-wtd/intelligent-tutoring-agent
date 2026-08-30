import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(testDir, "..", "..");
const installScript = path.join(repositoryRoot, "scripts", "install-agent-runtime.ps1");
const startScript = path.join(repositoryRoot, "scripts", "start-agent-runtime.ps1");
const smokeScript = path.join(repositoryRoot, "scripts", "smoke-agent-runtime.ps1");
const smokeShellScript = path.join(repositoryRoot, "scripts", "smoke-agent-runtime.sh");
const pwsh = process.env.PWSH_EXE || "pwsh.exe";
const gitBash = "C:\\Program Files\\Git\\bin\\bash.exe";

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    windowsHide: true,
    timeout: 20_000,
    ...options,
  });
  if (result.error) throw result.error;
  return result;
}


async function runHandleHelperScenario(mode) {
  const root = await mkdtemp(path.join(os.tmpdir(), "agent-runtime-handle-helper-"));
  const harness = path.join(root, "handle-helper-harness.ps1");
  const source = String.raw`param(
  [Parameter(Mandatory = $true)]
  [string]$StartScript,
  [Parameter(Mandatory = $true)]
  [ValidateSet("restore-failure", "launch-failure")]
  [string]$Mode
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($StartScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw "start script did not parse" }
$helper = $ast.Find({
  param($node)
  $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Start-ProcessWithoutInheritedConsolePipes"
}, $true)
if (-not $helper) { throw "handle helper not found" }
Invoke-Expression $helper.Extent.Text

function Assert-Harness([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

$script:mode = $Mode
$script:cleared = [Collections.Generic.List[long]]::new()
$script:restored = [Collections.Generic.List[long]]::new()
$script:child = $null
$getStandardHandle = {
  param([int]$StandardHandleId)
  return [IntPtr]::new(1000 + [Math]::Abs($StandardHandleId))
}
$getHandleFlags = {
  param([IntPtr]$Handle)
  return [uint32]1
}
$setHandleInheritance = {
  param([IntPtr]$Handle, [bool]$Inheritable)
  $value = $Handle.ToInt64()
  if ($Inheritable) {
    $script:restored.Add($value)
    if ($script:mode -eq "restore-failure" -and $value -eq 1010) {
      throw "injected restore failure"
    }
  } else {
    $script:cleared.Add($value)
  }
}
$startProcessInvoker = {
  param([hashtable]$Parameters)
  if ($script:mode -eq "launch-failure") {
    throw "injected start failure"
  }
  $childParameters = @{
    FilePath = Join-Path $PSHOME "pwsh.exe"
    ArgumentList = @("-NoProfile", "-Command", "Start-Sleep -Seconds 60")
    WindowStyle = "Hidden"
    PassThru = $true
  }
  $script:child = Start-Process @childParameters
  return $script:child
}

try {
  $caughtMessage = $null
  try {
    $helperParameters = @{
      StartProcessParameters = @{}
      StartProcessInvoker = $startProcessInvoker
      GetStandardHandle = $getStandardHandle
      GetHandleFlags = $getHandleFlags
      SetHandleInheritance = $setHandleInheritance
    }
    Start-ProcessWithoutInheritedConsolePipes @helperParameters | Out-Null
    throw "expected helper failure"
  } catch {
    $caughtMessage = $_.Exception.Message
  }

  Assert-Harness (($script:cleared -join ",") -eq "1010,1011,1012") "not every inheritable handle was cleared"
  Assert-Harness (($script:restored -join ",") -eq "1010,1011,1012") "not every changed handle was restored"

  if ($Mode -eq "restore-failure") {
    Assert-Harness ($null -ne $script:child) "child process was not created"
    $script:child.Refresh()
    Assert-Harness $script:child.HasExited "child process survived handle restoration failure"
    Assert-Harness ($caughtMessage -eq "Agent Runtime launch failed because inherited standard handles could not be restored; the started process tree was terminated.") "unsafe or unstable restoration error"
  } else {
    Assert-Harness ($null -eq $script:child) "launch failure unexpectedly created a child"
    Assert-Harness ($caughtMessage -eq "injected start failure") "launch error was not preserved"
  }

  [ordered]@{
    mode = $Mode
    cleared = $script:cleared.Count
    restored = $script:restored.Count
    child_exited = if ($script:child) { $script:child.HasExited } else { $null }
  } | ConvertTo-Json -Compress
} finally {
  if ($script:child) {
    $script:child.Refresh()
    if (-not $script:child.HasExited) {
      Stop-Process -Id $script:child.Id -Force -ErrorAction SilentlyContinue
      $script:child.WaitForExit()
    }
    $script:child.Dispose()
  }
}
`;

  try {
    await writeFile(harness, source, "utf8");
    return run(pwsh, ["-NoProfile", "-File", harness, "-StartScript", startScript, "-Mode", mode]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function runTaskkillFallbackTreeScenario() {
  const root = await mkdtemp(path.join(os.tmpdir(), "agent-runtime-taskkill-tree-"));
  const harness = path.join(root, "taskkill-tree-harness.ps1");
  const source = String.raw`param(
  [Parameter(Mandatory = $true)]
  [string]$StartScript
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($StartScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw "start script did not parse" }
$helper = $ast.Find({
  param($node)
  $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Start-ProcessWithoutInheritedConsolePipes"
}, $true)
if (-not $helper) { throw "handle helper not found" }
Invoke-Expression $helper.Extent.Text

function Assert-Harness([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

$treeScript = Join-Path $PSScriptRoot "tree-root.ps1"
$treePidFile = Join-Path $PSScriptRoot "tree-pids.txt"
@'
param(
  [Parameter(Mandatory = $true)]
  [string]$PidFile
)
$descendant = Start-Process -FilePath (Join-Path $PSHOME "pwsh.exe") -ArgumentList @(
  "-NoProfile",
  "-Command",
  "Start-Sleep -Seconds 60"
) -WindowStyle Hidden -PassThru
[IO.File]::WriteAllLines($PidFile, @([string]$PID, [string]$descendant.Id))
Start-Sleep -Seconds 60
'@ | Set-Content -LiteralPath $treeScript -Encoding utf8

$script:restored = [Collections.Generic.List[long]]::new()
$script:rootProcess = $null
$script:descendantId = 0
$getStandardHandle = {
  param([int]$StandardHandleId)
  return [IntPtr]::new(1000 + [Math]::Abs($StandardHandleId))
}
$getHandleFlags = {
  param([IntPtr]$Handle)
  return [uint32]1
}
$setHandleInheritance = {
  param([IntPtr]$Handle, [bool]$Inheritable)
  if ($Inheritable) {
    $script:restored.Add($Handle.ToInt64())
    if ($Handle.ToInt64() -eq 1010) {
      throw "injected restore failure"
    }
  }
}
$startProcessInvoker = {
  param([hashtable]$Parameters)
  $script:rootProcess = Start-Process -FilePath (Join-Path $PSHOME "pwsh.exe") -ArgumentList @(
    "-NoProfile",
    "-File",
    $treeScript,
    "-PidFile",
    $treePidFile
  ) -WindowStyle Hidden -PassThru
  $deadline = [DateTime]::UtcNow.AddSeconds(10)
  while (-not (Test-Path -LiteralPath $treePidFile) -and [DateTime]::UtcNow -lt $deadline) {
    $script:rootProcess.Refresh()
    if ($script:rootProcess.HasExited) { throw "tree root exited before publishing descendant pid" }
    Start-Sleep -Milliseconds 50
  }
  if (-not (Test-Path -LiteralPath $treePidFile)) { throw "timed out waiting for process tree" }
  $pids = @(Get-Content -LiteralPath $treePidFile | ForEach-Object { [int]$_ })
  if ($pids.Count -ne 2 -or $pids[0] -ne $script:rootProcess.Id) { throw "invalid process tree pid fixture" }
  $script:descendantId = $pids[1]
  if (-not (Get-Process -Id $script:descendantId -ErrorAction SilentlyContinue)) { throw "descendant did not remain running" }
  return $script:rootProcess
}
$killProcessTree = {
  param([Diagnostics.Process]$Process)
  throw "injected Process.Kill(true) failure"
}

try {
  $caughtMessage = $null
  try {
    Start-ProcessWithoutInheritedConsolePipes -StartProcessParameters @{} -StartProcessInvoker $startProcessInvoker -GetStandardHandle $getStandardHandle -GetHandleFlags $getHandleFlags -SetHandleInheritance $setHandleInheritance -KillProcessTree $killProcessTree | Out-Null
    throw "expected helper failure"
  } catch {
    $caughtMessage = $_.Exception.Message
  }

  Assert-Harness ($null -ne $script:rootProcess) "root process was not created"
  Assert-Harness ($script:descendantId -gt 0) "descendant process was not created"
  Assert-Harness (($script:restored -join ",") -eq "1010,1011,1012") "not every changed handle was restored"

  $deadline = [DateTime]::UtcNow.AddSeconds(10)
  do {
    $rootAlive = $null -ne (Get-Process -Id $script:rootProcess.Id -ErrorAction SilentlyContinue)
    $descendantAlive = $null -ne (Get-Process -Id $script:descendantId -ErrorAction SilentlyContinue)
    if (-not $rootAlive -and -not $descendantAlive) { break }
    Start-Sleep -Milliseconds 50
  } while ([DateTime]::UtcNow -lt $deadline)

  Assert-Harness (-not $rootAlive) "taskkill fallback left the root process running"
  Assert-Harness (-not $descendantAlive) "taskkill fallback left a descendant process running"
  Assert-Harness ($caughtMessage -eq "Agent Runtime launch failed because inherited standard handles could not be restored; the started process tree was terminated.") "unsafe or unstable process-tree cleanup error"

  [ordered]@{
    restored = $script:restored.Count
    root_exited = -not $rootAlive
    descendant_exited = -not $descendantAlive
  } | ConvertTo-Json -Compress
} finally {
  if ($script:rootProcess) {
    & (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) "taskkill.exe") /PID ([string]$script:rootProcess.Id) /T /F *> $null
    $script:rootProcess.Dispose()
  }
  if ($script:descendantId -gt 0) {
    Stop-Process -Id $script:descendantId -Force -ErrorAction SilentlyContinue
  }
}
`;

  try {
    await writeFile(harness, source, "utf8");
    return run(pwsh, ["-NoProfile", "-File", harness, "-StartScript", startScript], { timeout: 30_000 });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function runConservativeCleanupScenario(mode) {
  const root = await mkdtemp(path.join(os.tmpdir(), "agent-runtime-conservative-cleanup-"));
  const harness = path.join(root, "conservative-cleanup-harness.ps1");
  const source = String.raw`param(
  [Parameter(Mandatory = $true)]
  [string]$StartScript,
  [Parameter(Mandatory = $true)]
  [ValidateSet("orphan-after-primary-kill", "taskkill-nonzero-root-exit")]
  [string]$Mode
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($StartScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw "start script did not parse" }
$helper = $ast.Find({
  param($node)
  $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Start-ProcessWithoutInheritedConsolePipes"
}, $true)
if (-not $helper) { throw "handle helper not found" }
Invoke-Expression $helper.Extent.Text

function Assert-Harness([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

$rootScript = Join-Path $PSScriptRoot "cleanup-root.ps1"
$signalFile = Join-Path $PSScriptRoot "spawn-child.signal"
$descendantPidFile = Join-Path $PSScriptRoot "descendant.pid"
@'
param(
  [Parameter(Mandatory = $true)]
  [string]$Mode,
  [Parameter(Mandatory = $true)]
  [string]$SignalFile,
  [Parameter(Mandatory = $true)]
  [string]$DescendantPidFile
)
if ($Mode -eq "orphan-after-primary-kill") {
  while (-not (Test-Path -LiteralPath $SignalFile)) {
    Start-Sleep -Milliseconds 20
  }
  $descendant = Start-Process -FilePath (Join-Path $PSHOME "pwsh.exe") -ArgumentList @(
    "-NoProfile",
    "-Command",
    "Start-Sleep -Seconds 60"
  ) -WindowStyle Hidden -PassThru
  [IO.File]::WriteAllText($DescendantPidFile, [string]$descendant.Id)
  exit 0
}
Start-Sleep -Seconds 60
'@ | Set-Content -LiteralPath $rootScript -Encoding utf8

$script:mode = $Mode
$script:rootProcess = $null
$script:descendantId = 0
$script:restored = [Collections.Generic.List[long]]::new()
$getStandardHandle = {
  param([int]$StandardHandleId)
  return [IntPtr]::new(1000 + [Math]::Abs($StandardHandleId))
}
$getHandleFlags = {
  param([IntPtr]$Handle)
  return [uint32]1
}
$setHandleInheritance = {
  param([IntPtr]$Handle, [bool]$Inheritable)
  if ($Inheritable) {
    $script:restored.Add($Handle.ToInt64())
    if ($Handle.ToInt64() -eq 1010) {
      throw "injected restore failure"
    }
  }
}
$startProcessInvoker = {
  param([hashtable]$Parameters)
  $script:rootProcess = Start-Process -FilePath (Join-Path $PSHOME "pwsh.exe") -ArgumentList @(
    "-NoProfile",
    "-File",
    $rootScript,
    "-Mode",
    $script:mode,
    "-SignalFile",
    $signalFile,
    "-DescendantPidFile",
    $descendantPidFile
  ) -WindowStyle Hidden -PassThru
  return $script:rootProcess
}
$killProcessTree = {
  param([Diagnostics.Process]$Process)
  if ($script:mode -eq "orphan-after-primary-kill") {
    [IO.File]::WriteAllText($signalFile, "spawn")
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while (-not (Test-Path -LiteralPath $descendantPidFile) -and [DateTime]::UtcNow -lt $deadline) {
      Start-Sleep -Milliseconds 20
    }
    if (-not (Test-Path -LiteralPath $descendantPidFile)) { throw "root did not publish orphan pid" }
    $script:descendantId = [int](Get-Content -LiteralPath $descendantPidFile -Raw)
    $Process.WaitForExit(10000) | Out-Null
    if (-not $Process.HasExited) { throw "root did not exit after spawning orphan" }
  }
  throw "injected Process.Kill(true) failure"
}
$taskKillInvoker = {
  param([string]$FilePath, [string[]]$ArgumentList, [int]$TimeoutMilliseconds)
  if ($script:mode -ne "taskkill-nonzero-root-exit") {
    throw "taskkill must not run after the stable root process exited"
  }
  Stop-Process -Id $script:rootProcess.Id -Force -ErrorAction Stop
  $script:rootProcess.WaitForExit(10000) | Out-Null
  return [pscustomobject]@{
    Completed = $true
    ExitCode = 128
  }
}

try {
  $caughtMessage = $null
  try {
    $helperParameters = @{
      StartProcessParameters = @{}
      StartProcessInvoker = $startProcessInvoker
      GetStandardHandle = $getStandardHandle
      GetHandleFlags = $getHandleFlags
      SetHandleInheritance = $setHandleInheritance
      KillProcessTree = $killProcessTree
    }
    if ($Mode -eq "taskkill-nonzero-root-exit") {
      $helperParameters.TaskKillInvoker = $taskKillInvoker
    }
    Start-ProcessWithoutInheritedConsolePipes @helperParameters | Out-Null
    throw "expected helper failure"
  } catch {
    $caughtMessage = $_.Exception.Message
  }

  Assert-Harness (($script:restored -join ",") -eq "1010,1011,1012") "not every changed handle was restored"
  Assert-Harness ($caughtMessage -eq "Agent Runtime launch failed because inherited standard handles could not be restored, and cleanup of the started process tree could not be confirmed.") "unsafe cleanup result: $caughtMessage"
  $script:rootProcess.Refresh()
  Assert-Harness $script:rootProcess.HasExited "root process should have exited in the conservative cleanup scenario"

  if ($Mode -eq "orphan-after-primary-kill") {
    Assert-Harness ($script:descendantId -gt 0) "orphan descendant was not created"
    $descendantAlive = $null -ne (Get-Process -Id $script:descendantId -ErrorAction SilentlyContinue)
    Assert-Harness $descendantAlive "fixture orphan should remain alive until finally cleanup"
  }

  [ordered]@{
    mode = $Mode
    message = $caughtMessage
    root_exited = $script:rootProcess.HasExited
    orphan_observed = ($Mode -eq "orphan-after-primary-kill")
  } | ConvertTo-Json -Compress
} finally {
  if ($script:rootProcess) {
    try {
      $script:rootProcess.Refresh()
      if (-not $script:rootProcess.HasExited) {
        & (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) "taskkill.exe") /PID ([string]$script:rootProcess.Id) /T /F *> $null
      }
    } catch {}
    $script:rootProcess.Dispose()
  }
  if ($script:descendantId -gt 0) {
    Stop-Process -Id $script:descendantId -Force -ErrorAction SilentlyContinue
  }
}
`;

  try {
    await writeFile(harness, source, "utf8");
    return run(pwsh, ["-NoProfile", "-File", harness, "-StartScript", startScript, "-Mode", mode], { timeout: 30_000 });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function runRealHandleRoundTripScenario() {
  const root = await mkdtemp(path.join(os.tmpdir(), "agent-runtime-real-handle-roundtrip-"));
  const harness = path.join(root, "real-handle-roundtrip.ps1");
  const source = String.raw`param(
  [Parameter(Mandatory = $true)]
  [string]$StartScript
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($StartScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw "start script did not parse" }
$helper = $ast.Find({
  param($node)
  $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq "Start-ProcessWithoutInheritedConsolePipes"
}, $true)
if (-not $helper) { throw "handle helper not found" }
Invoke-Expression $helper.Extent.Text

if (-not ("AgentRuntimeTest.HandleProbe" -as [type])) {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace AgentRuntimeTest {
  public static class HandleProbe {
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

function Get-HandleFlags([IntPtr]$Handle) {
  [uint32]$flags = 0
  if (-not [AgentRuntimeTest.HandleProbe]::GetHandleInformation($Handle, [ref]$flags)) {
    throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }
  return $flags
}

function Set-InheritFlag([IntPtr]$Handle, [bool]$Inheritable) {
  $flags = if ($Inheritable) { [AgentRuntimeTest.HandleProbe]::HANDLE_FLAG_INHERIT } else { 0 }
  if (-not [AgentRuntimeTest.HandleProbe]::SetHandleInformation(
    $Handle,
    [AgentRuntimeTest.HandleProbe]::HANDLE_FLAG_INHERIT,
    $flags
  )) {
    throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }
}

$handles = [Collections.Generic.List[IntPtr]]::new()
$originalFlags = @{}
$child = $null
try {
  foreach ($standardHandleId in @(-10, -11, -12)) {
    $handle = [AgentRuntimeTest.HandleProbe]::GetStdHandle($standardHandleId)
    if ($handle -eq [IntPtr]::Zero -or $handle -eq [IntPtr]::new(-1)) { continue }
    try {
      $flags = Get-HandleFlags $handle
    } catch {
      continue
    }
    $key = [string]$handle.ToInt64()
    if (-not $originalFlags.ContainsKey($key)) {
      $handles.Add($handle)
      $originalFlags[$key] = $flags
    }
  }
  if ($handles.Count -eq 0) { throw "no valid standard handles were available" }

  Set-InheritFlag $handles[0] $true
  $beforeFlags = @{}
  $expectedClearedHandles = [Collections.Generic.List[IntPtr]]::new()
  foreach ($handle in $handles) {
    $flags = Get-HandleFlags $handle
    $beforeFlags[[string]$handle.ToInt64()] = $flags
    if (($flags -band [AgentRuntimeTest.HandleProbe]::HANDLE_FLAG_INHERIT) -ne 0) {
      $expectedClearedHandles.Add($handle)
    }
  }
  if ($expectedClearedHandles.Count -eq 0) { throw "failed to create an inheritable standard handle" }

  $startProcessInvoker = {
    param([hashtable]$Parameters)
    foreach ($handle in $expectedClearedHandles) {
      $flags = Get-HandleFlags $handle
      if (($flags -band [AgentRuntimeTest.HandleProbe]::HANDLE_FLAG_INHERIT) -ne 0) {
        throw "an inheritable standard handle remained set during child creation"
      }
    }
    Start-Process @Parameters
  }
  $child = Start-ProcessWithoutInheritedConsolePipes -StartProcessParameters @{
    FilePath = Join-Path $PSHOME "pwsh.exe"
    ArgumentList = @("-NoProfile", "-Command", "Start-Sleep -Milliseconds 100")
    WindowStyle = "Hidden"
    PassThru = $true
  } -StartProcessInvoker $startProcessInvoker
  $child.WaitForExit()

  foreach ($handle in $handles) {
    $key = [string]$handle.ToInt64()
    if ((Get-HandleFlags $handle) -ne $beforeFlags[$key]) {
      throw "standard handle inherit flags changed across a successful launch"
    }
  }

  [ordered]@{
    handles_checked = $handles.Count
    inheritable_handles_cleared = $expectedClearedHandles.Count
    child_exited = $child.HasExited
  } | ConvertTo-Json -Compress
} finally {
  if ($child) {
    $child.Refresh()
    if (-not $child.HasExited) {
      Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue
      $child.WaitForExit()
    }
    $child.Dispose()
  }
  foreach ($handle in $handles) {
    $key = [string]$handle.ToInt64()
    if ($originalFlags.ContainsKey($key)) {
      $wasInheritable = ($originalFlags[$key] -band [AgentRuntimeTest.HandleProbe]::HANDLE_FLAG_INHERIT) -ne 0
      Set-InheritFlag $handle $wasInheritable
    }
  }
}
`;

  try {
    await writeFile(harness, source, "utf8");
    return run(pwsh, ["-NoProfile", "-File", harness, "-StartScript", startScript]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function freePort() {
  const server = net.createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.equal(typeof address, "object");
  const port = address.port;
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function createRuntimeFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "agent-runtime-scripts-"));
  const runtimeDir = path.join(root, "apps", "agent-runtime");
  await mkdir(path.join(runtimeDir, "dist"), { recursive: true });
  await mkdir(path.join(root, "scripts"), { recursive: true });
  await writeFile(path.join(root, "scripts", "start-agent-runtime.ps1"), "# fixture\n", "utf8");
  const serverSource = `
const http = require("node:http");
const host = process.env.AGENT_RUNTIME_HOST;
const port = Number(process.env.AGENT_RUNTIME_PORT);
const token = process.env.AGENT_RUNTIME_TOKEN;
const server = http.createServer((request, response) => {
  if (request.url === "/v1/health") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ status: "ok", protocol_version: "1.0", upstream_commit: "fixture", node_version: process.versions.node }));
    return;
  }
  if (request.url === "/v1/diagnostics") {
    if (request.headers.authorization !== "Bearer " + token) {
      response.writeHead(401, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: { code: "unauthorized" } }));
      return;
    }
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ status: "ok" }));
    return;
  }
  response.writeHead(404).end();
});
server.listen(port, host);
process.on("SIGTERM", () => server.close(() => process.exit(0)));
`;
  await writeFile(path.join(runtimeDir, "dist", "index.js"), serverSource, "utf8");
  await writeFile(path.join(runtimeDir, "package.json"), JSON.stringify({ name: "fixture", private: true }), "utf8");
  return root;
}

async function stopManagedRuntime(root) {
  const pidPath = path.join(root, ".agent-data", "runtime-state", "runtime.pid");
  try {
    const pid = Number((await readFile(pidPath, "utf8")).trim());
    if (Number.isInteger(pid) && pid > 0) process.kill(pid, "SIGTERM");
  } catch {}
}

test("scripts encode the required runtime safety invariants", async () => {
  const [install, start, smoke, smokeSh] = await Promise.all([
    readFile(installScript, "utf8"),
    readFile(startScript, "utf8"),
    readFile(smokeScript, "utf8"),
    readFile(smokeShellScript, "utf8"),
  ]);

  assert.match(install, /Node\.js 24/);
  assert.match(install, /pnpm 11/);
  assert.match(start, /AGENT_RUNTIME_HOST\s*=\s*["']127\.0\.0\.1["']/);
  assert.match(start, /WindowStyle\s*=\s*["']Hidden["']/);
  assert.match(start, /HANDLE_FLAG_INHERIT/);
  assert.match(start, /\/v1\/health/);
  assert.match(start, /dist[\\/]index\.js/);
  const launchBlock = start.match(/\$process\s*=\s*Start-ProcessWithoutInheritedConsolePipes\s*@\{[\s\S]*?\n\s*\}/)?.[0] ?? "";
  assert.match(launchBlock, /RedirectStandardOutput/);
  assert.doesNotMatch(launchBlock, /AGENT_(?:RUNTIME_TOKEN|CAPABILITY_SECRET)/);
  assert.match(start, /safe|contain|outside/i);
  assert.match(smoke, /pnpm 11/);
  assert.match(smokeSh, /pnpm 11/);
  assert.match(smokeSh, /--config\s+-/);
  assert.doesNotMatch(smokeSh, /Authorization:\s*Bearer\s*\$\{?AGENT_RUNTIME_TOKEN/);
});

test("install rejects unsupported Node and pnpm majors before install", async () => {
  const root = await createRuntimeFixture();
  const fakeBin = path.join(root, "fake-bin");
  await mkdir(fakeBin, { recursive: true });
  const originalPath = process.env.PATH;
  try {
    await writeFile(path.join(fakeBin, "node.cmd"), "@echo off\r\necho v23.9.0\r\n", "utf8");
    await writeFile(path.join(fakeBin, "pnpm.cmd"), "@echo off\r\necho 11.0.0\r\n", "utf8");
    let result = run(pwsh, ["-NoProfile", "-File", installScript, "-RepositoryRoot", root, "-SkipStartupRegistration"], {
      env: { ...process.env, PATH: `${fakeBin};${originalPath}` },
    });
    assert.notEqual(result.status, 0, result.stdout + result.stderr);
    assert.match(result.stdout + result.stderr, /requires Node\.js 24/i);

    await writeFile(path.join(fakeBin, "node.cmd"), "@echo off\r\necho v24.1.0\r\n", "utf8");
    await writeFile(path.join(fakeBin, "pnpm.cmd"), "@echo off\r\necho 10.9.0\r\n", "utf8");
    result = run(pwsh, ["-NoProfile", "-File", installScript, "-RepositoryRoot", root, "-SkipStartupRegistration"], {
      env: { ...process.env, PATH: `${fakeBin};${originalPath}` },
    });
    assert.notEqual(result.status, 0, result.stdout + result.stderr);
    assert.match(result.stdout + result.stderr, /requires pnpm 11/i);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("handle restoration failure restores every handle and terminates the created child", async () => {
  const result = await runHandleHelperScenario("restore-failure");
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.deepEqual(JSON.parse(result.stdout.trim()), {
    mode: "restore-failure",
    cleared: 3,
    restored: 3,
    child_exited: true,
  });
});

test("Start-Process failure still restores every changed handle", async () => {
  const result = await runHandleHelperScenario("launch-failure");
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.deepEqual(JSON.parse(result.stdout.trim()), {
    mode: "launch-failure",
    cleared: 3,
    restored: 3,
    child_exited: null,
  });
});

test("taskkill fallback terminates a real root process and every descendant", async () => {
  const result = await runTaskkillFallbackTreeScenario();
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.deepEqual(JSON.parse(result.stdout.trim()), {
    restored: 3,
    root_exited: true,
    descendant_exited: true,
  });
});

test("root exit after spawning a post-kill orphan is reported as cleanup unconfirmed", async () => {
  const result = await runConservativeCleanupScenario("orphan-after-primary-kill");
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const evidence = JSON.parse(result.stdout.trim());
  assert.equal(evidence.mode, "orphan-after-primary-kill");
  assert.match(evidence.message, /cleanup of the started process tree could not be confirmed/i);
  assert.equal(evidence.root_exited, true);
  assert.equal(evidence.orphan_observed, true);
});

test("nonzero taskkill result remains unconfirmed even when the root exits", async () => {
  const result = await runConservativeCleanupScenario("taskkill-nonzero-root-exit");
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const evidence = JSON.parse(result.stdout.trim());
  assert.equal(evidence.mode, "taskkill-nonzero-root-exit");
  assert.match(evidence.message, /cleanup of the started process tree could not be confirmed/i);
  assert.equal(evidence.root_exited, true);
  assert.equal(evidence.orphan_observed, false);
});

test("successful launch restores the actual Windows standard handle inherit flags", async () => {
  const result = await runRealHandleRoundTripScenario();
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const evidence = JSON.parse(result.stdout.trim());
  assert.ok(evidence.handles_checked >= 1);
  assert.ok(evidence.inheritable_handles_cleared >= 1);
  assert.equal(evidence.child_exited, true);
});

test("start returns to a capturing caller while its loopback-only hidden Node process remains healthy and secret-free", async () => {
  const root = await createRuntimeFixture();
  const port = await freePort();
  const token = "runtime-token-command-line-canary";
  const capabilitySecret = "capability-secret-command-line-canary";
  const envFile = path.join(root, ".env");
  await writeFile(envFile, `AGENT_RUNTIME_TOKEN=${token}\nAGENT_CAPABILITY_SECRET=${capabilitySecret}\nAGENT_SIDECAR_ROOT=.agent-data/sidecars\n`, "utf8");

  try {
    const started = run(pwsh, ["-NoProfile", "-File", startScript, "-RepositoryRoot", root, "-EnvironmentFile", envFile, "-Port", String(port), "-HealthTimeoutSeconds", "15"]);
    assert.equal(started.status, 0, started.stdout + started.stderr);
    assert.match(started.stdout, /healthy/i);

    const pid = Number((await readFile(path.join(root, ".agent-data", "runtime-state", "runtime.pid"), "utf8")).trim());
    assert.ok(Number.isInteger(pid) && pid > 0);
    const commandLineResult = run(pwsh, ["-NoProfile", "-Command", `(Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}').CommandLine`]);
    assert.equal(commandLineResult.status, 0, commandLineResult.stdout + commandLineResult.stderr);
    assert.doesNotMatch(commandLineResult.stdout, new RegExp(token));
    assert.doesNotMatch(commandLineResult.stdout, new RegExp(capabilitySecret));
    assert.match(commandLineResult.stdout, /dist[\\/]index\.js/i);

    const health = await fetch(`http://127.0.0.1:${port}/v1/health`).then((response) => response.json());
    assert.equal(health.status, "ok");
    assert.equal(health.protocol_version, "1.0");

    const smoke = run(pwsh, ["-NoProfile", "-File", smokeScript, "-Origin", `http://127.0.0.1:${port}`, "-Token", token]);
    assert.equal(smoke.status, 0, smoke.stdout + smoke.stderr);

    const bash = run(gitBash, [smokeShellScript], {
      env: { ...process.env, AGENT_RUNTIME_ORIGIN: `http://127.0.0.1:${port}`, AGENT_RUNTIME_TOKEN: token },
    });
    assert.equal(bash.status, 0, bash.stdout + bash.stderr);

    for (const name of ["agent-runtime.stdout.log", "agent-runtime.stderr.log"]) {
      await readFile(path.join(root, ".agent-data", "logs", name), "utf8");
    }
  } finally {
    await stopManagedRuntime(root);
    await new Promise((resolve) => setTimeout(resolve, 250));
    await rm(root, { recursive: true, force: true });
  }
});

test("start rejects sidecar paths escaping the managed data root without disturbing an unrelated service", async () => {
  const root = await createRuntimeFixture();
  const port = await freePort();
  const unrelated = http.createServer((_request, response) => response.end("still-running"));
  unrelated.listen(0, "127.0.0.1");
  await once(unrelated, "listening");
  const unrelatedAddress = unrelated.address();
  assert.equal(typeof unrelatedAddress, "object");
  const envFile = path.join(root, ".env");
  await writeFile(envFile, "AGENT_RUNTIME_TOKEN=test-token\nAGENT_CAPABILITY_SECRET=test-secret\nAGENT_SIDECAR_ROOT=../escaped-sidecars\n", "utf8");

  try {
    const result = run(pwsh, ["-NoProfile", "-File", startScript, "-RepositoryRoot", root, "-EnvironmentFile", envFile, "-Port", String(port), "-HealthTimeoutSeconds", "2"]);
    assert.notEqual(result.status, 0, result.stdout + result.stderr);
    assert.match(result.stdout + result.stderr, /outside|managed data root|safe path/i);
    const response = await fetch(`http://127.0.0.1:${unrelatedAddress.port}`);
    assert.equal(await response.text(), "still-running");
  } finally {
    await new Promise((resolve, reject) => unrelated.close((error) => error ? reject(error) : resolve()));
    await stopManagedRuntime(root);
    await rm(root, { recursive: true, force: true });
  }
});
