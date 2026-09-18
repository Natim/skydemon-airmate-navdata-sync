from __future__ import annotations

from pathlib import Path

import pytest

from navdata_sync.config import ConfigError, init_config, load
from tests.helpers import write_config


def test_load_usb_target_string(tmp_path: Path) -> None:
    path = write_config(tmp_path, 'usb_target = "/media/RH D1000"')
    config = load(path)
    assert config.airmate_id == "TESTID"
    assert config.serial == "123456"
    assert config.usb_targets == (Path("/media/RH D1000"),)
    assert config.download_dir == tmp_path / "downloads"


def test_load_usb_targets_list(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """\
usb_targets = [
    "/media/LH D1000",
    "/media/RH D1000",
]
""",
    )
    config = load(path)
    assert config.usb_targets == (Path("/media/LH D1000"), Path("/media/RH D1000"))


def test_load_merges_and_deduplicates_usb_keys(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        'usb_target = "/media/RH D1000"\nusb_targets = ["/media/LH D1000", "/media/RH D1000"]\n',
    )
    config = load(path)
    assert config.usb_targets == (Path("/media/RH D1000"), Path("/media/LH D1000"))


def test_load_ignores_placeholder_usb_targets(tmp_path: Path) -> None:
    path = write_config(tmp_path, 'usb_targets = ["/run/media/YOUR_USER/LH D1000"]')
    assert load(path).usb_targets == ()


def test_load_rejects_example_placeholders(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    with pytest.raises(ConfigError, match="placeholder"):
        load(example)


def test_env_overrides_id_and_serial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_config(tmp_path)
    monkeypatch.setenv("AIRMATE_ID", "FROMENV")
    monkeypatch.setenv("AIRMATE_SERIAL", "999999")
    config = load(path)
    assert config.airmate_id == "FROMENV"
    assert config.serial == "999999"


def test_init_config_writes_example_once(tmp_path: Path) -> None:
    target = tmp_path / "out.toml"
    written = init_config(target)
    assert written == target
    assert "YOUR_AIRMATE_ID" in target.read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="already exists"):
        init_config(target)
