<#
.SYNOPSIS
    Simtabi installer: PowerShell bootstrap.

.DESCRIPTION
    Downloads installer.py + registry.json and hands off to Python.
    Body bytes flow URL -> disk; PowerShell layer only manages
    Python discovery, secure temp dir, and SHA256 verification.

.PARAMETER Product
    Which product to install (passed through to installer.py).

.PARAMETER Version
    Which version (defaults to the registry's default_version).

.PARAMETER InstallerBaseUrl
    Base URL hosting installer.py and registry.json.

.PARAMETER InstallerSha256
    SHA256 of installer.py (optional pin; warns if absent).

.PARAMETER AllowRoot
    Permit running elevated (refused by default).

.EXAMPLE
    irm https://get.simtabi.com/install.ps1 | iex

.EXAMPLE
    & ([scriptblock]::Create((irm https://get.simtabi.com/install.ps1))) `
        -Product claude-configurator -Yes
#>

[CmdletBinding()]
param(
    [string] $Product = '',
    [string] $Version = '',
    [string] $InstallerBaseUrl = $(if ($env:INSTALLER_BASE_URL) { $env:INSTALLER_BASE_URL } else { 'https://get.simtabi.com' }),
    [string] $InstallerSha256 = $env:INSTALLER_SHA256,
    [switch] $Yes,
    [switch] $Quiet,
    [switch] $DryRun,
    [switch] $AllowRoot,
    [switch] $WithPython,
    [switch] $List,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Extra
)

$ErrorActionPreference = 'Stop'
$MinPythonMajor = 3
$MinPythonMinor = 10

function Write-Info  { param([string] $Msg) Write-Host "[info] $Msg" -ForegroundColor Cyan }
function Write-Warn  { param([string] $Msg) Write-Host "[warn] $Msg" -ForegroundColor Yellow }
function Write-Fail  { param([string] $Msg) Write-Host "[fail] $Msg" -ForegroundColor Red; exit 1 }

# ----- elevated-user guard ------------------------------------------------- #
$isElevated = ([Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator)

if ($isElevated -and -not $AllowRoot) {
    Write-Fail "refusing to run as Administrator. Re-run without elevation, or pass -AllowRoot."
}

# ----- find Python --------------------------------------------------------- #
function Find-Python {
    foreach ($cand in @('python3.13', 'python3.12', 'python3.11', 'python3.10',
                        'python3', 'python', 'py')) {
        $exe = Get-Command $cand -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        try {
            $verStr = & $exe.Source -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>$null
            if (-not $verStr) { continue }
            $parts = $verStr.Trim() -split '\.'
            $maj = [int]$parts[0]; $min = [int]$parts[1]
            if (($maj -gt $MinPythonMajor) -or ($maj -eq $MinPythonMajor -and $min -ge $MinPythonMinor)) {
                return [pscustomobject]@{ Path = $exe.Source; Version = "$maj.$min" }
            }
        } catch { continue }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Fail "Python $MinPythonMajor.$MinPythonMinor+ not found on PATH.
       Install Python first (https://www.python.org/downloads/), then re-run.
       (If you have uv installed, you can pass -WithPython so the Python-side
       installer bootstraps a userspace Python.)"
}
Write-Info "Python $($py.Version) at $($py.Path)"

# ----- private temp dir ---------------------------------------------------- #
$Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("simtabi-installer-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null
# Restrict ACL to the current user (best-effort on non-NTFS)
try {
    $acl = Get-Acl $Tmp
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
        'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.SetAccessRule($rule)
    Set-Acl -Path $Tmp -AclObject $acl
} catch {
    Write-Warn "could not tighten ACL on $Tmp ($_)"
}

trap {
    if (Test-Path $Tmp) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Tmp }
    Write-Fail $_
}

# ----- download ----------------------------------------------------------- #
$installerUrl = "$InstallerBaseUrl/installer.py"
$registryUrl  = "$InstallerBaseUrl/registry.json"
$installerPath = Join-Path $Tmp 'installer.py'
$registryPath  = Join-Path $Tmp 'registry.json'

Write-Info "downloading installer.py + registry.json"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing -TimeoutSec 30
    Invoke-WebRequest -Uri $registryUrl  -OutFile $registryPath  -UseBasicParsing -TimeoutSec 30
} catch {
    Write-Fail "download failed: $_"
}

# ----- verify checksum ---------------------------------------------------- #
if ($InstallerSha256) {
    $actual = (Get-FileHash -Path $installerPath -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $InstallerSha256.ToLower()) {
        Write-Fail "sha256 mismatch: expected $InstallerSha256, got $actual"
    }
    Write-Info "installer.py sha256 verified"
} else {
    Write-Warn "no -InstallerSha256 pin: proceeding without integrity check"
}

# ----- execute ----------------------------------------------------------- #
$pyArgs = @($installerPath, '--registry', $registryPath)
if ($Product)     { $pyArgs += @('--product', $Product) }
if ($Version)     { $pyArgs += @('--version', $Version) }
if ($Yes)         { $pyArgs += '--yes' }
if ($Quiet)       { $pyArgs += '--quiet' }
if ($DryRun)      { $pyArgs += '--dry-run' }
if ($AllowRoot)   { $pyArgs += '--allow-root' }
if ($WithPython)  { $pyArgs += '--with-python' }
if ($List)        { $pyArgs += '--list' }
if ($Extra)       { $pyArgs += $Extra }

Write-Info "handing off to installer.py"
& $py.Path @pyArgs
$exitCode = $LASTEXITCODE

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Tmp
exit $exitCode
