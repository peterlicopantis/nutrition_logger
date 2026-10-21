"""Start MELB in the background and record startup errors."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
import argparse
import json
import subprocess
import os
import runpy
import traceback
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def stop_existing_app():
    """Only used by an explicit manual restart, never by Windows autostart."""
    environment = os.environ.copy()
    environment["MELB_RESTART_ROOT"] = str(ROOT)
    command = r"""
$ErrorActionPreference = 'Stop'
$melbRoot = [Environment]::GetEnvironmentVariable('MELB_RESTART_ROOT')
$melbApp = Join-Path $melbRoot 'app.py'
$melbRunner = Join-Path $melbRoot 'START_MELB_BACKGROUND.py'
$melbOwners = @(Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
# Verify every owner before stopping any process.
foreach ($melbOwner in $melbOwners) {
    $melbProcess = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $melbOwner)
    if (!$melbProcess) { continue }
    if (($melbProcess.Name -notin @('python.exe','pythonw.exe')) -or
        (!$melbProcess.CommandLine.Contains('"' + $melbApp + '"') -and
         !$melbProcess.CommandLine.Contains('"' + $melbRunner + '"'))) {
        throw 'Port 8501 belongs to another program or MELB folder. It was left running.'
    }
}
foreach ($melbOwner in $melbOwners) {
    Stop-Process -Id $melbOwner -Force -ErrorAction SilentlyContinue
}
for ($melbAttempt = 0; $melbAttempt -lt 30; $melbAttempt++) {
    if (!@(Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue).Count) {
        if ($melbOwners.Count) { Write-Output 'Stopped the previous MELB server.' }
        exit 0
    }
    Start-Sleep -Milliseconds 200
}
throw 'The previous MELB server has not stopped. The new copy was not started.'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment, capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Could not stop the previous MELB server.")
    if result.stdout.strip():
        print(result.stdout.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start MELB Nutrition.")
    parser.add_argument("--restart", action="store_true", help="Replace this project's running server.")
    parser.add_argument("--foreground", action="store_true", help="Run in the current command window.")
    args = parser.parse_args(argv)

    os.chdir(ROOT)
    if args.restart:
        stop_existing_app()
    if args.foreground:
        runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
        return
    try:
        with urlopen("http://127.0.0.1:8501/manifest.json", timeout=2) as response:
            if json.load(response).get("name") == "MELB Nutrition":
                return
    except (OSError, ValueError):
        pass
    log_folder = ROOT / "logs"
    log_folder.mkdir(exist_ok=True)
    log_path = log_folder / "startup.log"
    if log_path.exists() and log_path.stat().st_size > 1_000_000:
        log_path.replace(log_folder / "startup.previous.log")
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        with redirect_stdout(log), redirect_stderr(log):
            print(f"\nMELB startup: {datetime.now().isoformat(timespec='seconds')}")
            try:
                runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
            except Exception:
                traceback.print_exc()
                raise

if __name__ == "__main__":
    main()
