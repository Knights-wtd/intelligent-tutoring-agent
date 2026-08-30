from pathlib import Path

import pytest

from tutor_api.vault.storage import VaultPathError, VaultStorage, normalize_relative_path


def test_atomic_write_round_trip_and_no_temp_files(tmp_path: Path) -> None:
    storage = VaultStorage(tmp_path / "vault")
    storage.atomic_write("notes/a.md", b"alpha")
    assert storage.read_bytes("notes/a.md") == b"alpha"
    assert not list((tmp_path / "vault" / "notes").glob("*.tmp"))


@pytest.mark.parametrize(
    "path", ["../x", "/absolute", "C:/windows", "\\\\server\\share", "a/../../b", "a/./b"]
)
def test_rejects_escaping_paths(path: str) -> None:
    with pytest.raises(VaultPathError):
        normalize_relative_path(path)


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    storage = VaultStorage(tmp_path / "vault")
    link = storage.root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not available")
    with pytest.raises(VaultPathError):
        storage.atomic_write("link/escape.md", b"no")
