#!/usr/bin/env python3
"""Entry point kept at the repo root; the logic lives in navdata_sync/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from navdata_sync.cli import main
except ModuleNotFoundError as exc:
    # The shebang is deliberately generic, so this is what an unactivated
    # virtualenv looks like rather than a broken checkout.
    raise SystemExit(
        f"❌ dépendance manquante: {exc.name}\n"
        "   activez votre virtualenv, ou: pip install -e ."
    ) from exc

if __name__ == "__main__":
    raise SystemExit(main())
