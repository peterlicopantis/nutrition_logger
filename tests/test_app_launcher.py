"""Manual restarts replace only this project's server; tests never stop a process."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("melb_launcher", ROOT / "START_MELB_BACKGROUND.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class AppLauncherTests(unittest.TestCase):
    def test_manual_restart_stops_before_running_current_app_in_foreground(self):
        calls = []
        with patch.object(launcher.os, "chdir"), \
             patch.object(launcher, "stop_existing_app", side_effect=lambda:calls.append("stop")), \
             patch.object(launcher.runpy, "run_path", side_effect=lambda *a,**k:calls.append("start")):
            launcher.main(["--restart", "--foreground"])
        self.assertEqual(calls, ["stop", "start"])

    def test_autostart_leaves_existing_app_running(self):
        with patch.object(launcher.os, "chdir"), \
             patch.object(launcher, "urlopen", return_value=io.BytesIO(b'{"name":"MELB Nutrition"}')), \
             patch.object(launcher, "stop_existing_app") as stop, \
             patch.object(launcher.runpy, "run_path") as start:
            launcher.main([])
        stop.assert_not_called()
        start.assert_not_called()

    def test_failed_restart_does_not_launch_a_duplicate(self):
        with patch.object(launcher.os, "chdir"), \
             patch.object(launcher, "stop_existing_app", side_effect=RuntimeError("another app owns port")), \
             patch.object(launcher.runpy, "run_path") as start:
            with self.assertRaises(RuntimeError):
                launcher.main(["--restart", "--foreground"])
        start.assert_not_called()

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell required")
    def test_restart_process_verification_with_mocked_windows_commands(self):
        with patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([],0,"","")) as mocked:
            launcher.stop_existing_app()
            command = mocked.call_args.args[0][-1]
        fixtures = [
            ([], True, False),
            ([{"name":"pythonw.exe","path":str(ROOT / "START_MELB_BACKGROUND.py")}], True, True),
            ([{"name":"python.exe","path":str(ROOT / "app.py")}], True, True),
            ([{"name":"python.exe","path":r"C:\DifferentProject\app.py"}], False, False),
            ([{"name":"other.exe","path":str(ROOT / "app.py")}], False, False),
            ([{"name":"python.exe","path":str(ROOT / "app.py")},
              {"name":"other.exe","path":"other"}], False, False),
        ]
        mocks = r"""
$script:fixture = ConvertFrom-Json $env:MELB_LAUNCH_TEST
$script:stopped = $false
function Get-NetTCPConnection {
    if (!$script:stopped) {
        for ($i=0; $i -lt $script:fixture.Count; $i++) {
            [pscustomobject]@{OwningProcess=1000+$i}
        }
    }
}
function Get-CimInstance {
    param($ClassName,$Filter)
    $id = [int]($Filter -replace 'ProcessId = ','') - 1000
    $entry = $script:fixture[$id]
    [pscustomobject]@{Name=$entry.name;CommandLine=('python "'+$entry.path+'"')}
}
function Stop-Process {
    param($Id,[switch]$Force,$ErrorAction)
    $script:stopped=$true
    Write-Output 'TEST_STOPPED'
}
function Start-Sleep { param($Milliseconds) }
"""
        for owners, success, stopped in fixtures:
            with self.subTest(owners=owners):
                env = os.environ.copy()
                env["MELB_RESTART_ROOT"] = str(ROOT)
                env["MELB_LAUNCH_TEST"] = json.dumps(owners)
                result = subprocess.run(
                    ["powershell.exe","-NoProfile","-NonInteractive","-Command",mocks+command],
                    capture_output=True,text=True,env=env,timeout=15)
                self.assertEqual(result.returncode == 0,success,result.stderr)
                self.assertEqual("TEST_STOPPED" in result.stdout,stopped,result.stdout)

    def test_batch_file_uses_explicit_manual_restart(self):
        text = (ROOT / "RUN_MELB_APP.bat").read_text()
        self.assertIn('START_MELB_BACKGROUND.py" --restart --foreground',text)
