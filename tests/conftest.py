"""Clear identifying env vars so tests never inherit the developer's subscription."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_airmate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIRMATE_ID", raising=False)
    monkeypatch.delenv("AIRMATE_SERIAL", raising=False)
