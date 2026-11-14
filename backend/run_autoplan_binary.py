#!/usr/bin/env python3
"""Standalone PyInstaller binary entrypoint for AutoPlan."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AUTOPLAN_NO_EVENTLET", "1")

from planaieditor.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main() or 0)
