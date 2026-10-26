"""Generate only SIMULATED files in a new temporary cwd; never call Azure."""

import json
import os
import tempfile
from pathlib import Path

from support import BRANDING, TOOL, simulated_snapshot


if __name__ == "__main__":
    snapshot, _ = simulated_snapshot()
    previous = Path.cwd()
    run = Path(tempfile.mkdtemp(prefix="case06-SIMULATED-"))
    try:
        os.chdir(run)
        print(json.dumps(TOOL.write_report(snapshot, BRANDING), allow_nan=False))
    finally:
        os.chdir(previous)
