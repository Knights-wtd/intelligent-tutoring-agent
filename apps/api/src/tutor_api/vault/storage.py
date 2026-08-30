from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path, PurePosixPath


class VaultPathError(ValueError):
    pass


class VaultConflictError(RuntimeError):
    def __init__(self, code: str, *, actual_hash: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.actual_hash = actual_hash


_DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_relative_path(value: str) -> str:
    raw = value.strip()
    if not raw or "\x00" in raw or raw.startswith(("/", "\\", "//")) or _DRIVE.match(raw):
        raise VaultPathError("vault_path_invalid")
    raw = raw.replace("\\", "/")
    segments = raw.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise VaultPathError("vault_path_invalid")
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise VaultPathError("vault_path_invalid")
    normalized = path.as_posix()
    if normalized.startswith("//") or ":" in path.parts[0]:
        raise VaultPathError("vault_path_invalid")
    return normalized


class VaultStorage:
    def __init__(self, root: Path, *, anchor_root: Path | None = None) -> None:
        if anchor_root is None:
            self.root = root.resolve()
            self.root.mkdir(parents=True, exist_ok=True)
        else:
            self.root = self._ensure_anchored_root(root, anchor_root)

    @staticmethod
    def _ensure_anchored_root(root: Path, anchor_root: Path) -> Path:
        anchor = anchor_root.resolve(strict=True)
        logical_root = root if root.is_absolute() else root.absolute()
        try:
            relative = logical_root.relative_to(anchor)
        except ValueError as error:
            raise VaultPathError("vault_path_escape") from error

        current = anchor
        for segment in relative.parts:
            current /= segment
            current.mkdir(exist_ok=True)
            if current.resolve(strict=True) != current:
                raise VaultPathError("vault_path_escape")
        return logical_root

    def resolve(self, relative_path: str, *, require_exists: bool = False) -> Path:
        normalized = normalize_relative_path(relative_path)
        candidate = self.root.joinpath(*PurePosixPath(normalized).parts)
        parent = candidate.parent
        parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = parent.resolve(strict=True)
        if resolved_parent != self.root and self.root not in resolved_parent.parents:
            raise VaultPathError("vault_path_escape")
        resolved = resolved_parent / candidate.name
        if require_exists:
            actual = resolved.resolve(strict=True)
            if actual != self.root and self.root not in actual.parents:
                raise VaultPathError("vault_path_escape")
            return actual
        if resolved.exists() and resolved.is_symlink():
            actual = resolved.resolve(strict=True)
            if actual != self.root and self.root not in actual.parents:
                raise VaultPathError("vault_path_escape")
        return resolved

    def read_bytes(self, relative_path: str) -> bytes:
        return self.resolve(relative_path, require_exists=True).read_bytes()

    def atomic_write(self, relative_path: str, content: bytes) -> Path:
        target = self.resolve(relative_path)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            try:
                directory = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError:
                pass
            return target
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def move(self, source: str, target: str) -> Path:
        source_path = self.resolve(source, require_exists=True)
        target_path = self.resolve(target)
        if target_path.exists():
            raise VaultConflictError("vault_target_exists")
        os.replace(source_path, target_path)
        return target_path

    def delete(self, relative_path: str) -> None:
        self.resolve(relative_path, require_exists=True).unlink()
