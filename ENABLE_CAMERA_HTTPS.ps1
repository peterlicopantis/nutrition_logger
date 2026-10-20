$ErrorActionPreference = 'Stop'

function Get-MelbTailscalePath {
    $melbCommand = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($melbCommand) { return $melbCommand.Source }
    $melbProgramFolders = @(
        [Environment]::GetFolderPath('ProgramFiles'),
        [Environment]::GetFolderPath('ProgramFilesX86')
    )
    foreach ($melbProgramFolder in $melbProgramFolders) {
        if (-not $melbProgramFolder) { continue }
        $melbCandidate = Join-Path $melbProgramFolder 'Tailscale\tailscale.exe'
        if (Test-Path -LiteralPath $melbCandidate -PathType Leaf) { return $melbCandidate }
    }
    throw 'Install Tailscale and sign in on this PC before enabling the live camera.'
}

function Invoke-MelbTailscale {
    param([string]$Executable, [string[]]$Arguments, [switch]$StreamOutput)
    $melbPreviousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        if ($StreamOutput) {
            & $Executable @Arguments 2>&1 | Out-Host
            return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = '' }
        }
        $melbOutput = & $Executable @Arguments 2>&1
        return [pscustomobject]@{
            ExitCode = $LASTEXITCODE
            Output = ($melbOutput | Out-String).Trim()
        }
    }
    finally { $ErrorActionPreference = $melbPreviousPreference }
}

function Get-MelbTailscaleJson {
    param([string]$Executable, [string[]]$Arguments)
    $melbResult = Invoke-MelbTailscale -Executable $Executable -Arguments $Arguments
    if ($melbResult.ExitCode -ne 0) {
        throw ("Tailscale could not be read. Run this setup as Administrator. " + $melbResult.Output)
    }
    try { return ($melbResult.Output | ConvertFrom-Json -ErrorAction Stop) }
    catch { throw 'Tailscale returned an unreadable status; update Tailscale and try again.' }
}

function Get-MelbProperty {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $melbProperty = $Object.PSObject.Properties[$Name]
    if ($null -eq $melbProperty) { return $null }
    return $melbProperty.Value
}

function Test-MelbPort443Used {
    param($Configuration)
    if ($null -ne (Get-MelbProperty $Configuration.TCP '443')) { return $true }
    foreach ($melbProperty in $Configuration.Web.PSObject.Properties) {
        if ($melbProperty.Name -match ':443$') { return $true }
    }
    foreach ($melbProperty in $Configuration.AllowFunnel.PSObject.Properties) {
        if ($melbProperty.Name -match ':443$' -and $melbProperty.Value -eq $true) { return $true }
    }
    return $false
}

function Get-MelbCameraServeState {
    param($Configuration, [string]$DnsName)
    foreach ($melbForeground in $Configuration.Foreground.PSObject.Properties) {
        if (Test-MelbPort443Used $melbForeground.Value) {
            throw 'Port 443 has a foreground Tailscale service. Close or reconfigure that service first; this setup has not changed it.'
        }
    }
    foreach ($melbFunnel in $Configuration.AllowFunnel.PSObject.Properties) {
        if ($melbFunnel.Name -match ':443$' -and $melbFunnel.Value -eq $true) {
            throw 'Port 443 is configured for public Tailscale Funnel. This private-camera setup will not change it. Reconfigure that service separately first.'
        }
    }
    $melbTcp = Get-MelbProperty $Configuration.TCP '443'
    if ($null -eq $melbTcp) {
        if (Test-MelbPort443Used $Configuration) {
            throw 'Port 443 has an existing Tailscale web configuration. This setup will not overwrite it.'
        }
        return 'available'
    }
    $melbWeb = Get-MelbProperty $Configuration.Web ($DnsName + ':443')
    $melbRoot = Get-MelbProperty $melbWeb.Handlers '/'
    if ($melbTcp.HTTPS -eq $true -and
        ([string]$melbRoot.Proxy).TrimEnd('/') -eq 'http://127.0.0.1:8501') {
        return 'ready'
    }
    throw 'Port 443 already serves another Tailscale target. This setup will not overwrite it. Reconfigure that service separately before trying again.'
}

function Enable-MelbCameraHttps {
    $melbExecutable = Get-MelbTailscalePath
    $melbStatus = Get-MelbTailscaleJson $melbExecutable @('status', '--json')
    if ($melbStatus.BackendState -ne 'Running') {
        throw 'Open Tailscale, sign in, and connect this PC before running camera setup again.'
    }
    $melbDnsName = ([string]$melbStatus.Self.DNSName).TrimEnd('.')
    if ($melbDnsName -notmatch '^[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+\.ts\.net$') {
        throw 'This PC needs a Tailscale .ts.net device name. Enable MagicDNS in Tailscale and try again.'
    }
    $melbConfiguration = Get-MelbTailscaleJson $melbExecutable @('serve', 'status', '--json')
    $melbState = Get-MelbCameraServeState $melbConfiguration $melbDnsName
    if ($melbState -eq 'available') {
        Write-Host 'Enabling private HTTPS for MELB on your Tailscale network.'
        Write-Host 'If Tailscale prints a setup link, open it and approve HTTPS as the account owner.'
        Write-Host 'Keep this window open during approval. If setup stops, approve the link and run this file again.'
        Write-Host 'Tailscale may ask you to acknowledge the device hostname appearing in public certificate records.'
        $melbResult = Invoke-MelbTailscale -Executable $melbExecutable -Arguments @(
            'serve', '--bg', '--https=443', 'http://127.0.0.1:8501'
        ) -StreamOutput
        if ($melbResult.ExitCode -ne 0) {
            throw 'HTTPS setup did not finish. Follow any Tailscale approval link above, then run this setup as Administrator again.'
        }
        $melbConfiguration = Get-MelbTailscaleJson $melbExecutable @('serve', 'status', '--json')
        if ((Get-MelbCameraServeState $melbConfiguration $melbDnsName) -ne 'ready') {
            throw 'HTTPS is not configured yet. Complete the Tailscale approval step and run this setup again.'
        }
    }
    Write-Host ''
    Write-Host ('Phone address: https://' + $melbDnsName)
    Write-Host 'Open this HTTPS address in Safari with Tailscale connected, then allow the camera.'
    Write-Host 'MELB must be running on this PC. Existing app autostart still applies.'
    Write-Host 'The private HTTPS proxy stays enabled across restarts; this setup only needs to run once.'
}

# Dot-sourcing exposes the functions for offline verification without running setup.
if ($MyInvocation.InvocationName -ne '.') {
    try { Enable-MelbCameraHttps }
    catch {
        Write-Host ''
        Write-Host $_.Exception.Message -ForegroundColor Red
        exit 1
    }
}
