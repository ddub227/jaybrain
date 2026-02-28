#!/usr/bin/env python3
"""Run a one-shot vault sync (manual trigger).

Usage:
    python scripts/vault_sync_now.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jaybrain.vault_sync import run_vault_sync  # noqa: E402

if __name__ == "__main__":
    result = run_vault_sync()
    print(f"Vault sync complete: {result}")
