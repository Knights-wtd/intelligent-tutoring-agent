param(
    [Parameter()]
    [string]$EnvPath = (Join-Path (Split-Path -Parent $PSScriptRoot) '.env')
)

$ErrorActionPreference = 'Stop'
$secure = Read-Host 'Enter FARO API Key (input is hidden)' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}

if ([string]::IsNullOrWhiteSpace($key)) {
    throw 'FARO API Key cannot be blank.'
}

$lines = if (Test-Path -LiteralPath $EnvPath) {
    [Collections.Generic.List[string]](Get-Content -LiteralPath $EnvPath)
} else {
    [Collections.Generic.List[string]]::new()
}
$replaced = $false
for ($index = 0; $index -lt $lines.Count; $index++) {
    if ($lines[$index] -match '^FARO_API_KEY=') {
        $lines[$index] = 'FARO_API_KEY=' + $key
        $replaced = $true
    }
}
if (-not $replaced) {
    $lines.Add('FARO_API_KEY=' + $key)
}
[IO.File]::WriteAllLines($EnvPath, $lines, [Text.UTF8Encoding]::new($false))
$key = $null
