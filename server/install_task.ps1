#Requires -Version 5.1
<#
.SYNOPSIS
    Register the desk-panel server as a login-scoped Scheduled Task.

.DESCRIPTION
    The server is the login signal: the phone holds its screen on exactly while
    the server answers, so the server must be launched by, and die with, the
    graphical session of a human user. A Windows Service has the same uptime and
    the wrong meaning -- it answers before anyone logs in, and the panel would
    light up for an empty room. See docs/adr/0010-login-signal-is-session-scoped.md.

    This script therefore has no -User and no -Password parameter anywhere. There
    is no code path here that can produce an S4U or Password logon type, which is
    how a task quietly becomes a service in disguise.

.PARAMETER Python
    An explicit interpreter to use. If it fails validation the script stops
    rather than searching -- an override that gets silently ignored is worse
    than no override at all.

.PARAMETER Firewall
    Also create the Private-profile inbound rule. Needs an elevated shell;
    registering the task itself does not.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File server\install_task.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $Python,
    [string] $Config,
    [string] $LogFile,
    [switch] $Firewall,
    [switch] $FirewallOnly,
    [switch] $NoStart,
    [switch] $Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Not a parameter. verify_login_scope.py hardcodes these same literals, and a
# renamed task would make the verifier report "not installed" about a perfectly
# good installation.
$TaskName = 'desk-panel'
$ServiceName = 'desk-panel'
$FirewallRuleName = 'desk-panel'
$MinimumPython = [version]'3.11'
$MaxLogBytes = 1MB

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ServerPy = Join-Path (Join-Path $RepoRoot 'server') 'server.py'
$ProbePy = Join-Path (Join-Path $RepoRoot 'server') 'probe.py'

function Write-Step { param([string] $Message) Write-Host "==> $Message" }
function Write-Note { param([string] $Message) Write-Host "    $Message" }

function Stop-WithError {
    param([string] $Message, [int] $Code = 1)
    Write-Host ''
    Write-Host "install_task.ps1: $Message" -ForegroundColor Red
    exit $Code
}

function Resolve-AbsolutePath {
    <#
        A relative path is resolved against the *shell's* current directory,
        which is where the caller typed it, and then stored absolute.

        Both halves matter. Stored relative, the pre-flight would check the
        path against the shell's cwd while the task resolved it against
        WorkingDirectory = the repo root, so every check could pass and the
        server still fail at the next login -- under pythonw, with no console,
        and for -LogFile before stdout is even redirected, so not even a log
        to explain it. server.py's config_search_paths states the contract
        this keeps: every launcher passes an absolute --config, so cwd never
        matters. It also stops Split-Path -Parent returning the empty string
        for a bare filename, which is a terminating error here.
    #>
    param([string] $Path)
    $base = (Get-Location -PSProvider FileSystem).ProviderPath
    return [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($base, $Path))
}

function Get-ConfiguredPort {
    param([string] $Path)
    $port = 8777
    try {
        $parsed = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($parsed.PSObject.Properties.Name -contains 'port') { $port = [int] $parsed.port }
    } catch {
        Write-Warning "could not read the port out of $Path; assuming $port."
    }
    return $port
}

function New-DeskPanelFirewallRule {
    param([int] $Port)
    if (-not (Test-Elevated)) {
        Stop-WithError (
            'creating the firewall rule needs an elevated shell. The task itself ' +
            'needs no admin, so do not re-run the whole installer elevated -- that ' +
            'would re-register it for whichever account elevated. From an elevated ' +
            'PowerShell run only: server\install_task.ps1 -FirewallOnly')
    }
    if ($null -ne (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue)) {
        Remove-NetFirewallRule -DisplayName $FirewallRuleName
    }
    New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $Port -Profile Private | Out-Null
    Write-Note "created the inbound rule for TCP $Port on the Private profile."
}

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# --------------------------------------------------------------------------
# Interpreter resolution
# --------------------------------------------------------------------------
# The interesting failure this guards against is not an absent Python, it is
# the wrong one. On the development machine `python` on PATH resolves into an
# unrelated project's virtualenv, and `py` follows it too because it honours
# VIRTUAL_ENV. Writing that path into the task produces something that works
# today and dies the day that folder is deleted -- at the next login, with no
# console to report it.

# One line, single quotes, no spaces: PowerShell 5.1 re-parses the arguments it
# hands a native executable and strips double quotes out of them, so a prettier
# multi-line probe arrives at the interpreter as a NameError.
$ProbeScript = "import sys,json;print(json.dumps({'exe':sys.executable,'version':list(sys.version_info[:3]),'prefix':sys.prefix,'base':sys.base_prefix}))"

function Get-RegistryPythonCandidates {
    # The primary source, and first for a reason: it is written by the real
    # installer and is unaffected by PATH, by VIRTUAL_ENV and by the console
    # language.
    $candidates = @()
    $hives = @(
        'HKCU:\SOFTWARE\Python\PythonCore',
        'HKLM:\SOFTWARE\Python\PythonCore',
        'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore'
    )
    foreach ($hive in $hives) {
        if (-not (Test-Path -LiteralPath $hive)) { continue }
        foreach ($tagKey in (Get-ChildItem -LiteralPath $hive -ErrorAction SilentlyContinue)) {
            $tag = $tagKey.PSChildName
            $installKey = Join-Path $tagKey.PSPath 'InstallPath'
            if (-not (Test-Path -LiteralPath $installKey)) { continue }
            $props = Get-ItemProperty -LiteralPath $installKey -ErrorAction SilentlyContinue
            if ($null -eq $props) { continue }

            $exe = $null
            if ($props.PSObject.Properties.Name -contains 'ExecutablePath') {
                $exe = $props.ExecutablePath
            }
            if ([string]::IsNullOrWhiteSpace($exe) -and
                ($props.PSObject.Properties.Name -contains '(default)')) {
                $root = $props.'(default)'
                if (-not [string]::IsNullOrWhiteSpace($root)) {
                    $exe = Join-Path $root 'python.exe'
                }
            }
            if ([string]::IsNullOrWhiteSpace($exe)) { continue }

            # "3.13-32" and "3.13-arm64" are the cross-bit tags; they sort below
            # the native build of the same version.
            $parsed = $null
            if (-not [version]::TryParse(($tag -replace '-.*$', ''), [ref] $parsed)) { continue }
            $candidates += [pscustomobject]@{
                Path    = $exe
                Version = $parsed
                Native  = -not ($tag -match '-')
                Source  = "registry $hive\$tag"
            }
        }
    }
    return @($candidates | Sort-Object `
        @{ Expression = 'Native'; Descending = $true }, `
        @{ Expression = 'Version'; Descending = $true })
}

function Get-LauncherPythonCandidates {
    $launcher = Get-Command -Name 'py.exe' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $launcher) { return @() }

    $candidates = @()
    foreach ($line in @(& $launcher.Source -0p)) {
        # Only the tagged lines. When a virtualenv is active the launcher's
        # starred default line carries no -V: tag, so this excludes it by
        # construction rather than by a special case.
        if ($line -match '^\s*-V:(?<tag>\d+\.\d+)(?<arch>-\S+)?\s+\*?\s*(?<path>\S.*)$') {
            $parsed = $null
            if (-not [version]::TryParse($Matches['tag'], [ref] $parsed)) { continue }
            $candidates += [pscustomobject]@{
                Path    = $Matches['path'].Trim()
                Version = $parsed
                Native  = [string]::IsNullOrEmpty($Matches['arch'])
                Source  = "py -0p ($($Matches['tag']))"
            }
        }
    }
    return @($candidates | Sort-Object `
        @{ Expression = 'Native'; Descending = $true }, `
        @{ Expression = 'Version'; Descending = $true })
}

function Get-PathPythonCandidates {
    $candidates = @()
    foreach ($command in @(Get-Command -Name 'python.exe' -CommandType Application -ErrorAction SilentlyContinue)) {
        $candidates += [pscustomobject]@{
            Path    = $command.Source
            Version = $null
            Native  = $true
            Source  = 'PATH'
        }
    }
    return $candidates
}

function Test-PythonCandidate {
    <#
        Returns a resolved interpreter, or $null with the reason on stderr.
        $Strict turns every rejection into a hard stop -- used for -Python,
        where falling through to a search would ignore what the caller asked for.
    #>
    param(
        [string] $Path,
        [string] $Source,
        [switch] $Strict,
        [int] $Depth = 0
    )

    function Reject {
        param([string] $Why)
        if ($Strict) { Stop-WithError "-Python $Path : $Why" }
        Write-Verbose "skipping $Path ($Source): $Why"
        return $null
    }

    if ([string]::IsNullOrWhiteSpace($Path)) { return (Reject 'empty path') }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return (Reject 'no such file')
    }

    # The Store stub, checked before anything is executed. It is a zero-byte
    # app-execution alias: a task pointing at it opens the Microsoft Store
    # instead of starting the server -- silently, and only at the next login.
    $item = Get-Item -LiteralPath $Path
    if (($Path -match '\\Microsoft\\WindowsApps\\') -or ($item.Length -eq 0)) {
        return (Reject (
            'that is the Microsoft Store app-execution alias, not an interpreter. ' +
            'Install Python from python.org, or turn the alias off in ' +
            'Settings > Apps > Advanced > App execution aliases'))
    }

    # VIRTUAL_ENV/PYTHONHOME/PYTHONPATH cleared for the child, so the answer
    # describes the interpreter rather than this shell.
    # -WhatIf:$false throughout: this is internal bookkeeping that is undone in
    # the finally block, not the operation the caller asked to preview. Left to
    # inherit, -WhatIf would skip the clearing and the probe would describe this
    # shell instead of the interpreter.
    $saved = @{}
    foreach ($name in @('VIRTUAL_ENV', 'PYTHONHOME', 'PYTHONPATH')) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name)
        Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue -WhatIf:$false
    }
    try {
        $raw = & $Path -c $ProbeScript
    } catch {
        return (Reject "could not run it: $($_.Exception.Message)")
    } finally {
        foreach ($name in $saved.Keys) {
            if ($null -ne $saved[$name]) {
                Set-Item -Path "Env:$name" -Value $saved[$name] -WhatIf:$false
            }
        }
    }

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($raw | Out-String))) {
        return (Reject 'it did not answer a version probe')
    }
    try {
        $info = ($raw | Out-String).Trim() | ConvertFrom-Json
    } catch {
        return (Reject 'its version probe printed something unparsable')
    }

    # A virtualenv is not rejected, it is stepped out of: the base interpreter
    # is the one that outlives the project the venv belongs to. One level only
    # -- a second indirection is a malformed install, not a nested venv.
    if ($info.prefix -ne $info.base) {
        if ($Depth -ge 1) { return (Reject 'its base prefix is itself a virtualenv') }
        $base = Join-Path $info.base 'python.exe'
        Write-Note "$Path is a virtualenv; using its base interpreter instead,"
        Write-Note "so the task survives that project being deleted."
        return (Test-PythonCandidate -Path $base -Source "$Source (base prefix)" -Strict:$Strict -Depth ($Depth + 1))
    }

    $version = [version]('{0}.{1}.{2}' -f $info.version[0], $info.version[1], $info.version[2])
    if ($version -lt $MinimumPython) {
        return (Reject "Python $version is below the $MinimumPython floor in server/CLAUDE.md")
    }

    # pythonw is what makes the task windowless; python.exe would flash a
    # console at every single login.
    $pythonw = Join-Path (Split-Path -Parent $info.exe) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
        return (Reject 'there is no pythonw.exe beside it')
    }

    return [pscustomobject]@{
        Python  = $info.exe
        Pythonw = $pythonw
        Version = $version
        Source  = $Source
    }
}

function Resolve-PythonInterpreter {
    if (-not [string]::IsNullOrWhiteSpace($Python)) {
        return (Test-PythonCandidate -Path $Python -Source 'the -Python argument' -Strict)
    }
    foreach ($group in @(
        (Get-RegistryPythonCandidates),
        (Get-LauncherPythonCandidates),
        (Get-PathPythonCandidates))) {
        foreach ($candidate in $group) {
            $resolved = Test-PythonCandidate -Path $candidate.Path -Source $candidate.Source
            if ($null -ne $resolved) { return $resolved }
        }
    }
    Stop-WithError (
        'found no usable Python 3.11+. Install one from python.org (not the ' +
        'Microsoft Store build), or pass -Python <path to python.exe>.')
}

# --------------------------------------------------------------------------
# Post-registration check
# --------------------------------------------------------------------------

function Get-XmlText {
    # XPath by local-name(): the task XML carries a default namespace, and this
    # sidesteps it without a namespace manager. Also strict-mode safe, where a
    # missing element would otherwise throw instead of answering "absent".
    param($Node, [string] $Name)
    if ($null -eq $Node) { return $null }
    $child = $Node.SelectSingleNode("*[local-name()='$Name']")
    if ($null -eq $child) { return $null }
    return $child.InnerText.Trim()
}

function Assert-TaskShape {
    <#
        Reads back what was actually registered and asserts the same fields
        verify_login_scope.check_windows_task asserts, from the same XML. The
        cmdlet parameters that produce them are renamed and two are inverted,
        so this keeps PT0S an observation rather than a belief -- and fails
        loudly if a future PowerShell regresses.
    #>
    param([string] $ExpectedCommand)

    $document = [xml](Export-ScheduledTask -TaskName $TaskName -TaskPath '\')
    $root = $document.DocumentElement
    $settings = $root.SelectSingleNode("*[local-name()='Settings']")
    $principal = $root.SelectSingleNode("*[local-name()='Principals']/*[local-name()='Principal']")
    $triggers = $root.SelectSingleNode("*[local-name()='Triggers']")
    $command = Get-XmlText -Node $root.SelectSingleNode("*[local-name()='Actions']/*[local-name()='Exec']") -Name 'Command'

    $triggerNames = @()
    if ($null -ne $triggers) {
        foreach ($child in $triggers.ChildNodes) { $triggerNames += $child.LocalName }
    }

    $failures = @()
    if (($triggerNames -join ',') -ne 'LogonTrigger') {
        $failures += "Triggers are [$($triggerNames -join ', ')]; the only allowed trigger is LogonTrigger"
    }
    $checks = @(
        @{ Name = 'LogonType'; Actual = (Get-XmlText -Node $principal -Name 'LogonType'); Expected = 'InteractiveToken' },
        @{ Name = 'ExecutionTimeLimit'; Actual = (Get-XmlText -Node $settings -Name 'ExecutionTimeLimit'); Expected = 'PT0S' },
        @{ Name = 'DisallowStartIfOnBatteries'; Actual = (Get-XmlText -Node $settings -Name 'DisallowStartIfOnBatteries'); Expected = 'false' },
        @{ Name = 'StopIfGoingOnBatteries'; Actual = (Get-XmlText -Node $settings -Name 'StopIfGoingOnBatteries'); Expected = 'false' }
    )
    foreach ($check in $checks) {
        if ($check.Actual -ne $check.Expected) {
            $failures += "$($check.Name) is '$($check.Actual)', must be '$($check.Expected)'"
        }
    }

    # Enabled is the one field where absent is correct: the exporter omits it at
    # its default, and the default is enabled. Only an explicit false is wrong.
    $enabled = Get-XmlText -Node $settings -Name 'Enabled'
    if ($enabled -eq 'false') { $failures += 'Settings/Enabled is false -- the task is disabled' }
    if ($command -ne $ExpectedCommand) {
        $failures += "Actions/Exec/Command is '$command', expected '$ExpectedCommand'"
    }

    if ($failures.Count -gt 0) {
        Write-Host ''
        foreach ($failure in $failures) { Write-Host "    $failure" -ForegroundColor Red }
        Stop-WithError 'the registered task does not have the shape ADR 0010 requires.'
    }
    Write-Note 'read back: one LogonTrigger, InteractiveToken, PT0S, batteries false, enabled.'
}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $ServerPy -PathType Leaf)) {
    Stop-WithError "cannot find $ServerPy -- run this script from inside the repository."
}

if ($Uninstall) {
    Write-Step 'Removing the Scheduled Task'
    if ($null -ne (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
        if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister-ScheduledTask')) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Note "task '$TaskName' removed."
        }
    } else {
        Write-Note "no task named '$TaskName'; nothing to do."
    }
    if ($Firewall) {
        if (-not (Test-Elevated)) {
            Stop-WithError 'removing the firewall rule needs an elevated shell.'
        }
        Remove-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
        Write-Note "firewall rule '$FirewallRuleName' removed if it existed."
    }
    Write-Note 'config.json and the logs were left alone.'
    exit 0
}

# The firewall rule is the one step that needs admin, and it must be reachable
# without re-running the registration. Elevating the whole installer re-runs
# Register-ScheduledTask as whoever elevated: where the desk user is standard
# and UAC asks for a separate administrator, that silently replaces a correct
# task with one triggered by the admin's logon, so the panel lights for the
# wrong person and never for the right one.
if ($FirewallOnly) {
    Write-Step 'Firewall rule only -- not touching the Scheduled Task'
    if ([string]::IsNullOrWhiteSpace($Config)) {
        $Config = Join-Path (Join-Path $RepoRoot 'server') 'config.json'
    }
    $Config = Resolve-AbsolutePath $Config
    New-DeskPanelFirewallRule -Port (Get-ConfiguredPort -Path $Config)
    exit 0
}

# -- refuse anything of system scope ---------------------------------------
Write-Step 'Checking the scope this will run in'

$currentSid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
if ($currentSid -in @('S-1-5-18', 'S-1-5-19', 'S-1-5-20')) {
    Stop-WithError (
        'this shell is SYSTEM or a service account. A task registered for it ' +
        'would never correspond to a human logging in at the screen.')
}

if ($null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
    Stop-WithError (
        "a Windows Service named '$ServiceName' exists. It answers before anyone " +
        'logs in and at the lock screen, so the panel would light for an empty ' +
        "room whatever this task does. Remove it first (elevated): sc.exe delete $ServiceName")
}

if (Test-Elevated) {
    Write-Warning (
        'this shell is elevated. Registering the task needs no admin rights, and ' +
        'elevating invites registering it for the wrong account. Use -Firewall ' +
        'alone from an elevated shell if that is what you came for.')
}
$me = "$env:USERDOMAIN\$env:USERNAME"
Write-Note "task principal: $me"

# -- interpreter -----------------------------------------------------------
Write-Step 'Resolving the Python interpreter'
$interpreter = Resolve-PythonInterpreter
Write-Note "python  : $($interpreter.Python)"
Write-Note "pythonw : $($interpreter.Pythonw)"
Write-Note "version : $($interpreter.Version)  (resolved via $($interpreter.Source))"

# -- config ----------------------------------------------------------------
Write-Step 'Validating the configuration'
if ([string]::IsNullOrWhiteSpace($Config)) {
    $Config = Join-Path (Join-Path $RepoRoot 'server') 'config.json'
}
$Config = Resolve-AbsolutePath $Config
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    Stop-WithError (
        "there is no $Config. Create it first:`n" +
        "    Copy-Item server\config.example.json server\config.json`n" +
        '  then edit it: tickers, city, brapi token, port.')
}
# The real python, not pythonw: this one has to be able to print its complaint.
# stderr is deliberately left flowing to the console rather than captured --
# redirecting a native command's stderr in PowerShell 5.1 wraps each line in a
# NativeCommandError, which $ErrorActionPreference='Stop' then turns fatal.
$configOutput = & $interpreter.Python $ServerPy --check-only --config $Config
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "$Config did not load (its complaint is above). Fix it before installing the task."
}
Write-Note ($configOutput | Out-String).Trim()

$port = Get-ConfiguredPort -Path $Config

# -- stop the previous instance --------------------------------------------
# Before the log is rotated and before anything is registered. Left running,
# it holds the log open so the rotation orphans the old process onto
# server.log.1, and it keeps answering on the port -- which makes the
# "already answers" guard below read our own stale instance as a
# hand-started server, skip the restart, and report success while the
# previous configuration goes on serving.
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing -and $existing.State -eq 'Running') {
    if ($PSCmdlet.ShouldProcess($TaskName, 'Stop-ScheduledTask')) {
        Write-Note 'stopping the previously installed task before replacing it.'
        Stop-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 2
    }
}

# -- log file --------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($LogFile)) {
    $LogFile = Join-Path (Join-Path $env:LOCALAPPDATA 'desk-panel') 'server.log'
}
$LogFile = Resolve-AbsolutePath $LogFile
$logDirectory = Split-Path -Parent $LogFile
if (-not (Test-Path -LiteralPath $logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
}
# server.py opens this in append mode and never rotates it. Low volume, but
# unbounded across months of daily logins, so trim it while we are here.
if (Test-Path -LiteralPath $LogFile -PathType Leaf) {
    if ((Get-Item -LiteralPath $LogFile).Length -gt $MaxLogBytes) {
        Move-Item -LiteralPath $LogFile -Destination "$LogFile.1" -Force
        Write-Note "rotated the previous log to $LogFile.1"
    }
}

# -- register --------------------------------------------------------------
Write-Step 'Registering the Scheduled Task'

$arguments = '"{0}" --config "{1}" --log-file "{2}"' -f $ServerPy, $Config, $LogFile
$action = New-ScheduledTaskAction -Execute $interpreter.Pythonw -Argument $arguments -WorkingDirectory $RepoRoot
# -User matters: without it the trigger fires on *any* user's logon.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
# Interactive is the cmdlet's spelling of the XML's InteractiveToken. Password
# and S4U both run without an interactive session -- a service in disguise.
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew
# Each of those four undoes a default that is wrong here:
#   AllowStartIfOnBatteries    -- the default never starts the task on a laptop
#   DontStopIfGoingOnBatteries -- the default stops it the moment you unplug
#   ExecutionTimeLimit 0       -- the default 72h kills the server on day four,
#                                 mid-session, and the panel goes dark for no
#                                 visible reason
#   IgnoreNew                  -- fast user switching must not start a second
#                                 server; allow_reuse_address is off on Windows
#                                 precisely so the second one fails loudly

$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'desk-panel PC server (login signal) -- see docs/adr/0010-login-signal-is-session-scoped.md'

if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -InputObject $task -Force | Out-Null
    Write-Note "registered '$TaskName', at log on, as $me."
    Assert-TaskShape -ExpectedCommand $interpreter.Pythonw
} else {
    Write-Note 'skipped (-WhatIf).'
    exit 0
}

# -- start it now ----------------------------------------------------------
if (-not $NoStart) {
    Write-Step 'Starting it now'
    & $interpreter.Python $ProbePy --host 127.0.0.1 --port $port --expect up | Out-Null
    if ($LASTEXITCODE -eq 0) {
        # Our own previous instance was stopped above, so whatever is still
        # holding the port is somebody else's -- a hand-started server, most
        # likely. Starting the task on top of it would just make it die with
        # EADDRINUSE, since allow_reuse_address is off on Windows.
        Write-Warning "something else already answers on port $port -- not starting the task."
        Write-Note 'Stop it and run Start-ScheduledTask desk-panel, or the task will'
        Write-Note "die with EADDRINUSE at the next login. Nothing you see on $port"
        Write-Note 'right now is being served by the task this script just registered.'
    } else {
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 3
        & $interpreter.Python $ProbePy --host 127.0.0.1 --port $port --expect up | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Note "answering on 127.0.0.1:$port."
        } else {
            Write-Warning "the task started but nothing answers on port $port yet. Check $LogFile"
        }
    }
}

# -- firewall and network profile ------------------------------------------
Write-Step 'Firewall'

$rule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
if ($Firewall) {
    New-DeskPanelFirewallRule -Port $port
} elseif ($null -eq $rule) {
    Write-Note "no firewall rule named '$FirewallRuleName'. From an elevated PowerShell,"
    Write-Note 'run only this -- not the whole installer, which would re-register the'
    Write-Note 'task for whichever account elevated:'
    Write-Host ""
    Write-Host "    server\install_task.ps1 -FirewallOnly"
    Write-Host ""
    Write-Note 'or, by hand:'
    Write-Host ""
    Write-Host "    New-NetFirewallRule -DisplayName `"$FirewallRuleName`" -Direction Inbound -Action Allow ``"
    Write-Host "      -Protocol TCP -LocalPort $port -Profile Private"
    Write-Host ""
    Write-Note 'Never forward this port on the router: the server has no authentication'
    Write-Note 'because it is only ever reachable from the LAN.'
} else {
    Write-Note "the inbound rule '$FirewallRuleName' already exists."
}

# A Private-profile rule admits nothing while the adapter is classified Public,
# and the phone then reports "offline" looking exactly like a server bug.
foreach ($netProfile in @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)) {
    if ($netProfile.NetworkCategory -eq 'Public') {
        Write-Warning (
            "the active network '$($netProfile.Name)' ($($netProfile.InterfaceAlias)) is " +
            'classified Public, so a Private-profile rule will not admit the phone.')
        Write-Host "    Set-NetConnectionProfile -InterfaceAlias '$($netProfile.InterfaceAlias)' -NetworkCategory Private"
        Write-Note 'Do not widen the rule to Public instead -- LAN-only is what lets'
        Write-Note 'the server have no authentication at all.'
    }
}

Write-Step 'Next'
Write-Note 'python server\verify_login_scope.py'
Write-Note 'and, from another device on the LAN (localhost proves nothing here):'
Write-Note '    python server/probe.py --host <pc-ip> --expect up'
exit 0
