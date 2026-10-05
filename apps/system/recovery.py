"""Verified database/source backups; restoration only into a new isolated database."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import uuid
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from apps.backtester.config import load_env, build_db_config
from apps.system.processes import run_bounded
from core.utils.io import write_json


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def pgtool(name):
    found = shutil.which(name)
    if found:
        return found
    candidates = list(Path("/workspace/.local/pgserver-venv/lib").glob(f"python*/site-packages/pgserver/pginstall/bin/{name}"))
    if candidates:
        return str(candidates[0])
    raise RuntimeError("POSTGRES_TOOL_NOT_FOUND")


def parameters(config, database=None):
    return dict(host=config["host"], port=config["port"], user=config["user"],
                password=config["password"], dbname=database or config["database"], connect_timeout=5)


def inventory(config, database=None):
    with psycopg.connect(**parameters(config, database)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        return {name: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))).fetchone()[0]
                for name in tables}


def tool_environment(config, database):
    return dict(os.environ, PGHOST=str(config["host"]), PGPORT=str(config["port"]),
                PGUSER=config["user"], PGPASSWORD=config["password"], PGDATABASE=database)


def backup(destination, source_dir=None):
    load_env(); config = build_db_config()
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    before = inventory(config)
    dump = destination / "database.dump"
    rc = run_bounded([pgtool("pg_dump"), "--format=custom", "--no-owner",
                     "--exclude-table-data=public.user_broker_credentials", "--file", str(dump)],
                     cwd=destination, env=tool_environment(config, config["database"]), timeout=1800)
    if rc:
        raise RuntimeError("BACKUP_DUMP_FAILED")
    dump.chmod(0o600)
    files = {dump.name: digest(dump)}
    source_files = {}
    if source_dir:
        source = Path(source_dir).resolve()
        if not source.is_dir() or source == destination or source in destination.parents or destination in source.parents:
            raise ValueError("SOURCE_REQUIRES_DISTINCT_PUBLIC_CACHE_DIRECTORY")
        archive = destination / "sources.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            for path in sorted(source.rglob("*")):
                if (path.is_file() and not path.is_symlink() and
                        not any(part.startswith(".") for part in path.relative_to(source).parts)
                        and (path.suffix.lower() in {".xml", ".xbrl", ".zip", ".csv", ".html"}
                             or re.fullmatch(r"[a-f0-9]{64}\.(bin|json)", path.name))
                        and not any(word in path.name.lower() for word in ("token", "credential", "secret", "account", "config"))):
                    name = path.relative_to(source).as_posix()
                    source_files[name] = {"bytes": path.stat().st_size, "sha256": digest(path)}
                    handle.add(path, arcname=name, recursive=False)
        archive.chmod(0o600)
        files[archive.name] = digest(archive)
    after = inventory(config)
    expected = {name: (0 if name == "user_broker_credentials" else count) for name, count in before.items()}
    manifest = {"format_version": 1, "source_database": config["database"],
                "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
                "files": files, "source_counts_before": before, "source_counts_after": after,
                "counts_stable": before == after, "credentials_included": False,
                "expected_restore_counts": expected, "excluded_data_tables": ["user_broker_credentials"],
                "source_files": source_files,
                "source_scope": "public-source cache only; do not supply credential directories"}
    write_json(destination / "manifest.json", manifest)
    return {"status": "PASS", "directory": str(destination), "counts_stable": before == after,
            "files": list(files), "source_file_count": len(source_files),
            "source_bytes": sum(f["bytes"] for f in source_files.values()), "credentials_included": False}


def verified_manifest(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    files = manifest.get("files", {})
    if manifest.get("format_version") != 1 or "database.dump" not in files or not set(files) <= {"database.dump", "sources.tar.gz"}:
        raise ValueError("INVALID_BACKUP_MANIFEST")
    for name, expected in files.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise ValueError("BACKUP_CHECKSUM_MISMATCH")
    return manifest


def extract_sources(archive, destination):
    with tarfile.open(archive, "r:gz") as handle:
        members = handle.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or "\\" in member.name or ":" in member.name or not member.isfile():
                raise ValueError("UNSAFE_SOURCE_ARCHIVE")
        Path(destination).mkdir(parents=True, exist_ok=False, mode=0o700)
        handle.extractall(destination, members=members)


def restore(directory, database=None):
    load_env(); config = build_db_config()
    directory = Path(directory).resolve()
    manifest = verified_manifest(directory)
    database = database or "quantpilot_restore_" + uuid.uuid4().hex[:12]
    if not re.fullmatch(r"quantpilot_restore_[a-z0-9_]{1,40}", database):
        raise ValueError("RESTORE_REQUIRES_NEW_ISOLATED_DATABASE_NAME")
    with psycopg.connect(**parameters(config, "postgres"), autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
            raise ValueError("RESTORE_DATABASE_ALREADY_EXISTS")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    rc = run_bounded([pgtool("pg_restore"), "--dbname", database, "--no-owner", "--no-privileges",
                      "--single-transaction", "--exit-on-error", str(directory / "database.dump")],
                     cwd=directory, env=tool_environment(config, database), timeout=1800)
    if rc:
        raise RuntimeError("RESTORE_FAILED_NEW_DATABASE_RETAINED_FOR_INSPECTION")
    counts = inventory(config, database)
    if manifest["counts_stable"] and counts != manifest.get("expected_restore_counts", manifest["source_counts_before"]):
        raise ValueError("RESTORED_ROW_COUNTS_MISMATCH")
    sources = None
    if "sources.tar.gz" in manifest["files"]:
        sources = directory / (database + "-sources")
        extract_sources(directory / "sources.tar.gz", sources)
        expected_sources = manifest.get("source_files", {})
        restored_sources = {p.relative_to(sources).as_posix() for p in sources.rglob("*") if p.is_file()}
        if expected_sources and restored_sources != set(expected_sources):
            raise ValueError("RESTORED_SOURCE_FILE_SET_MISMATCH")
        for name, info in expected_sources.items():
            path = sources / name
            if path.stat().st_size != info["bytes"] or digest(path) != info["sha256"]:
                raise ValueError("RESTORED_SOURCE_CHECKSUM_MISMATCH")
    report = {"status": "PASS", "database": database, "row_counts": counts,
              "source_directory": str(sources) if sources else None,
              "source_file_count": len(manifest.get("source_files", {})),
              "original_database_unchanged": True, "credentials_restored": False}
    write_json(directory / (database + "-verification.json"), report)
    return report
