"""Start MELB in the background and record startup errors."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
import json
import os
import runpy
import traceback
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent

def main():
    os.chdir(ROOT)
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
