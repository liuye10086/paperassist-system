"""Run with --help; omission of --execute only validates source and writes a plan."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.maintenance.recovery_drill import main

if __name__ == '__main__':
    raise SystemExit(main())
