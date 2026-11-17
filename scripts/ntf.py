#!/usr/bin/env python3
"""Run the source CLI without installing skills or modifying global Python paths."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from notetofilm_local.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
