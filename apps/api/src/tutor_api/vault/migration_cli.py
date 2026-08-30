"""Command-line entry point for permanent Vault migration phases."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from tutor_api.agent import models as agent_models  # noqa: F401
from tutor_api.core.config import Settings, get_settings
from tutor_api.core.database import create_engine_from_url
from tutor_api.identity import models as identity_models  # noqa: F401
from tutor_api.knowledge.storage import create_object_storage
from tutor_api.spaces import models as space_models  # noqa: F401
from tutor_api.vault.migration import (
    MigrationManifest,
    MigrationStatePublishError,
    VaultMigrator,
    load_manifest,
)

Handler = Callable[[argparse.Namespace], int]
_SERVICE_FACTORY: Callable[[argparse.Namespace], VaultMigrator] | None = None


def configure_service_factory(
    factory: Callable[[argparse.Namespace], VaultMigrator] | None,
) -> None:
    global _SERVICE_FACTORY
    _SERVICE_FACTORY = factory


def _json_value(value: Any) -> Any:
    if isinstance(value, (Path, UUID)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _emit(manifest: MigrationManifest, command: str, payload: dict[str, Any]) -> None:
    result_path = manifest.path.with_name(f"{command}-result.json")
    output = {**payload, "result_path": str(result_path)}
    temporary = result_path.with_name(result_path.name + ".tmp")
    temporary.write_text(
        json.dumps(_json_value(output), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(result_path)
    print(json.dumps(_json_value(output), ensure_ascii=False, sort_keys=True))


@contextmanager
def _service(args: argparse.Namespace) -> Iterator[VaultMigrator]:
    if _SERVICE_FACTORY is not None:
        service = _SERVICE_FACTORY(args)
        try:
            yield service
            service.session.commit()
        except MigrationStatePublishError:
            raise
        except Exception:
            service.session.rollback()
            raise
        return
    settings: Settings = get_settings()
    engine = create_engine_from_url(settings.database_url, app_env=settings.app_env)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        service = VaultMigrator(
            session=session,
            object_storage=create_object_storage(settings),
            vault_root=Path(args.vault_root or settings.agent_vault_root),
            artifact_root=Path(
                getattr(args, "artifact_root", None) or Path.cwd() / "artifacts" / "agent-migration"
            ),
        )
        yield service
        session.commit()
    except MigrationStatePublishError:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def _manifest(args: argparse.Namespace) -> MigrationManifest:
    return load_manifest(args.manifest)


def inventory_command(args: argparse.Namespace) -> int:
    with _service(args) as service:
        manifest = service.inventory(knowledge_base_id=args.knowledge_base_id)
    _emit(manifest, "inventory", {"manifest_path": str(manifest.path)})
    return 0


def copy_command(args: argparse.Namespace) -> int:
    manifest = _manifest(args)
    with _service(args) as service:
        result = service.copy(manifest)
    _emit(
        manifest,
        "copy",
        {
            "manifest_path": str(manifest.path),
            "copied": result.copied,
            "reused": result.reused,
            "conflicts": [asdict(item) for item in result.conflicts],
            "conflict_report_path": str(result.conflict_report_path),
        },
    )
    return int(bool(result.conflicts))


def verify_command(args: argparse.Namespace) -> int:
    manifest = _manifest(args)
    with _service(args) as service:
        result = service.verify(manifest)
    _emit(manifest, "verify", {"manifest_path": str(manifest.path), **asdict(result)})
    return int(bool(result.hash_mismatches) or result.source_file_count != result.vault_file_count)


def _state_command(args: argparse.Namespace, command: str) -> int:
    manifest = _manifest(args)
    with _service(args) as service:
        state = getattr(service, command.replace("-", "_"))(manifest)
    _emit(manifest, command, {"manifest_path": str(manifest.path), "state": asdict(state)})
    return 0


def activate_shadow_command(args: argparse.Namespace) -> int:
    return _state_command(args, "activate-shadow")


def cutover_command(args: argparse.Namespace) -> int:
    return _state_command(args, "cutover")


def rollback_command(args: argparse.Namespace) -> int:
    return _state_command(args, "rollback")


def _add_runtime_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vault-root", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vault-migration")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inventory = subcommands.add_parser("inventory")
    inventory.add_argument(
        "--knowledge-base-id", type=lambda value: __import__("uuid").UUID(value), required=True
    )
    inventory.add_argument("--artifact-root", type=Path)
    _add_runtime_paths(inventory)
    inventory.set_defaults(handler=inventory_command)
    handlers: dict[str, Handler] = {
        "copy": copy_command,
        "verify": verify_command,
        "activate-shadow": activate_shadow_command,
        "cutover": cutover_command,
        "rollback": rollback_command,
    }
    for name, handler in handlers.items():
        command = subcommands.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        _add_runtime_paths(command)
        command.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args) or 0)


def entrypoint(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except MigrationStatePublishError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
