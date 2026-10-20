"""Offline checks for the private camera HTTPS setup; never calls Tailscale."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

POWERSHELL = shutil.which("powershell.exe")
SETUP = Path(__file__).resolve().parents[1] / "ENABLE_CAMERA_HTTPS.ps1"
HOST = "melb-test.tailtest.ts.net"


def serving_configuration(target="http://127.0.0.1:8501"):
    return {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {f"{HOST}:443": {"Handlers": {"/": {"Proxy": target}}}},
    }


@unittest.skipUnless(POWERSHELL, "Windows PowerShell is unavailable")
class CameraHttpsSetupTests(unittest.TestCase):
    def run_powershell(self, script, fixture=None):
        environment = os.environ.copy()
        environment["MELB_CAMERA_TEST_FIXTURE"] = json.dumps(fixture or {})
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=20, env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def simulate(self, before=None, after=None, backend="Running", mutation_exit=0):
        escaped_path = str(SETUP).replace("'", "''")
        script = """
$ErrorActionPreference = 'Stop'
. '__SETUP__'
$script:melbFixture = $env:MELB_CAMERA_TEST_FIXTURE | ConvertFrom-Json
$script:melbCalls = New-Object System.Collections.Generic.List[string]
$script:melbMutations = 0
function Get-MelbTailscalePath { return 'fake-tailscale-never-executed.exe' }
function Invoke-MelbTailscale {
    param([string]$Executable, [string[]]$Arguments, [switch]$StreamOutput)
    $melbCall = $Arguments -join ' '
    $script:melbCalls.Add($melbCall)
    if ($melbCall -eq 'status --json') {
        $melbValue = $script:melbFixture.Status
    }
    elseif ($melbCall -eq 'serve status --json') {
        if ($script:melbMutations -gt 0) { $melbValue = $script:melbFixture.After }
        else { $melbValue = $script:melbFixture.Before }
    }
    elseif ($melbCall -eq 'serve --bg --https=443 http://127.0.0.1:8501') {
        $script:melbMutations++
        return [pscustomobject]@{ ExitCode=$script:melbFixture.MutationExit; Output='' }
    }
    else { throw ('Unexpected command: ' + $melbCall) }
    return [pscustomobject]@{ ExitCode=0; Output=($melbValue | ConvertTo-Json -Depth 20 -Compress) }
}
$melbOutcome = 'ready'
$melbMessage = ''
try { Enable-MelbCameraHttps }
catch { $melbOutcome = 'error'; $melbMessage = $_.Exception.Message }
[pscustomobject]@{
    Outcome=$melbOutcome
    Message=$melbMessage
    Mutations=$script:melbMutations
    Calls=@($script:melbCalls)
} | ConvertTo-Json -Depth 10 -Compress
""".replace("__SETUP__", escaped_path)
        return self.run_powershell(script, {
            "Status": {"BackendState": backend, "Self": {"DNSName": HOST + "."}},
            "Before": before or {},
            "After": after if after is not None else serving_configuration(),
            "MutationExit": mutation_exit,
        })

    def test_windows_powershell_can_parse_helper(self):
        escaped_path = str(SETUP).replace("'", "''")
        result = self.run_powershell("""
$melbTokens = $null
$melbErrors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    '__SETUP__', [ref]$melbTokens, [ref]$melbErrors
)
@{ Errors=@($melbErrors | ForEach-Object { $_.Message }) } | ConvertTo-Json -Compress
""".replace("__SETUP__", escaped_path))
        self.assertEqual(result["Errors"], [])

    def test_enables_private_background_proxy_and_checks_result(self):
        result = self.simulate()
        self.assertEqual(result["Outcome"], "ready", result)
        self.assertEqual(result["Mutations"], 1)
        self.assertEqual(result["Calls"], [
            "status --json", "serve status --json",
            "serve --bg --https=443 http://127.0.0.1:8501", "serve status --json",
        ])

    def test_existing_melb_proxy_is_idempotent(self):
        result = self.simulate(before=serving_configuration())
        self.assertEqual(result["Outcome"], "ready", result)
        self.assertEqual(result["Mutations"], 0)

    def test_conflicting_services_and_public_funnel_are_preserved(self):
        configurations = [
            serving_configuration("http://127.0.0.1:3000"),
            {"TCP": {"443": {"TCPForward": "127.0.0.1:2222"}}},
            {"Foreground": {"session": serving_configuration()}},
            dict(serving_configuration(), AllowFunnel={f"{HOST}:443": True}),
        ]
        for configuration in configurations:
            with self.subTest(configuration=configuration):
                result = self.simulate(before=configuration)
                self.assertEqual(result["Outcome"], "error", result)
                self.assertEqual(result["Mutations"], 0)

    def test_other_ports_do_not_block_private_proxy(self):
        other = {"TCP": {"8443": {"HTTPS": True}}, "Web": {
            f"{HOST}:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}},
        }}
        combined = serving_configuration()
        combined["TCP"].update(other["TCP"])
        combined["Web"].update(other["Web"])
        result = self.simulate(before=other, after=combined)
        self.assertEqual(result["Outcome"], "ready", result)
        self.assertEqual(result["Mutations"], 1)

    def test_disconnected_client_and_incomplete_consent_are_reported(self):
        disconnected = self.simulate(backend="NeedsLogin")
        self.assertEqual(disconnected["Outcome"], "error")
        self.assertEqual(disconnected["Mutations"], 0)
        self.assertIn("sign in", disconnected["Message"])
        for settings in ({"mutation_exit": 1}, {"after": {}}):
            with self.subTest(settings=settings):
                result = self.simulate(**settings)
                self.assertEqual(result["Outcome"], "error")
                self.assertIn("approval", result["Message"])


if __name__ == "__main__":
    unittest.main()
