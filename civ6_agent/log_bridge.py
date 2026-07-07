from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


STATE_PREFIX = "CIV6_AGENT_STATE\t"
COMMAND_PREFIX = "CIV6_AGENT_COMMAND\t"
BRIDGE_MOD_ID = "e5c9c7f4-7cc0-4c70-8cc6-6b7d7f700001"
BRIDGE_READY_MARKER = "CIV6_AGENT_BRIDGE_READY"
CIV6_STEAM_APP_ID = "289070"
CIV6_INSTALL_DIR_NAME = "Sid Meier's Civilization VI"


def support_root() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Sid Meier's Civilization VI"
        / "Firaxis Games"
        / "Sid Meier's Civilization VI"
    )


def steam_app_path() -> Path:
    return steam_install_root() / "Civ6.app"


def steam_libraryfolders_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "Steam" / "steamapps" / "libraryfolders.vdf"


def steam_default_library_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "Steam"


def steam_library_roots() -> list[Path]:
    roots = [steam_default_library_root()]
    vdf_path = steam_libraryfolders_path()
    if vdf_path.exists():
        with vdf_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped.startswith('"path"'):
                    continue
                parts = stripped.split('"')
                if len(parts) >= 4:
                    roots.append(Path(parts[3].replace("\\\\", "\\")))
    seen: set[Path] = set()
    result: list[Path] = []
    for root in roots:
        expanded = root.expanduser()
        if expanded not in seen:
            seen.add(expanded)
            result.append(expanded)
    return result


def steam_install_candidates() -> list[Path]:
    candidates = []
    env_root = os.environ.get("CIV6_STEAM_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    for library_root in steam_library_roots():
        candidates.append(library_root / "steamapps" / "common" / CIV6_INSTALL_DIR_NAME)
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def steam_downloading_candidates() -> list[Path]:
    return [
        library_root / "steamapps" / "downloading" / CIV6_STEAM_APP_ID
        for library_root in steam_library_roots()
    ]


def steam_appmanifest_candidates() -> list[Path]:
    return [
        library_root / "steamapps" / f"appmanifest_{CIV6_STEAM_APP_ID}.acf"
        for library_root in steam_library_roots()
    ]


def steam_appmanifest_path() -> Path | None:
    for path in steam_appmanifest_candidates():
        if path.exists():
            return path
    return None


def read_steam_appmanifest(path: Path | None = None) -> dict[str, str]:
    manifest_path = path or steam_appmanifest_path()
    values: dict[str, str] = {}
    if manifest_path is None or not manifest_path.exists():
        return values
    with manifest_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped.startswith('"'):
                continue
            parts = stripped.split('"')
            if len(parts) >= 4:
                values[parts[1]] = parts[3]
    values["_path"] = str(manifest_path)
    return values


def steam_install_root() -> Path:
    candidates = steam_install_candidates()
    for candidate in candidates:
        if (candidate / "Civ6.app").exists():
            return candidate
    for candidate in candidates:
        if candidate.exists() and steam_install_flavor_for_root(candidate) not in {"incomplete_or_empty", "not_found"}:
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def steam_install_flavor() -> str:
    return steam_install_flavor_for_root(steam_install_root())


def steam_install_flavor_for_root(root: Path) -> str:
    if (root / "Civ6.app").exists():
        return "macos_app"
    if (root / "LaunchPad" / "LaunchPad.exe").exists():
        return "windows_depot"
    if root.exists():
        meaningful_entries = [
            path
            for path in root.rglob("*")
            if path.name != ".DS_Store" and path.is_file()
        ]
        if not meaningful_entries:
            return "incomplete_or_empty"
        return "unknown_present"
    return "not_found"


def steam_download_status() -> list[dict[str, Any]]:
    return [
        {
            "path": str(path),
            "exists": path.exists(),
            "contains_macos_app": (path / "Civ6.app").exists(),
            "contains_windows_launcher": (path / "LaunchPad" / "LaunchPad.exe").exists(),
        }
        for path in steam_downloading_candidates()
    ]


def mods_dir() -> Path:
    return support_root() / "Mods"


def mods_sqlite_path() -> Path:
    return support_root() / "Mods.sqlite"


def app_options_path() -> Path:
    return support_root() / "AppOptions.txt"


def candidate_lua_log_paths() -> list[Path]:
    home = Path.home()
    paths = []
    env_path = os.environ.get("CIV6_LUA_LOG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.extend(
        [
            home / "Library" / "Application Support" / "Sid Meier's Civilization VI" / "Firaxis Games" / "Sid Meier's Civilization VI" / "Logs" / "Lua.log",
            home / "Library" / "Application Support" / "Sid Meier's Civilization VI" / "Logs" / "Lua.log",
            home / "Library" / "Application Support" / "Sid Meier's Civilization VI" / "Lua.log",
            home / "Documents" / "Aspyr" / "Sid Meier's Civilization VI" / "Logs" / "Lua.log",
            home / "Documents" / "My Games" / "Sid Meier's Civilization VI" / "Logs" / "Lua.log",
        ]
    )
    seen: set[Path] = set()
    result = []
    for path in paths:
        expanded = path.expanduser()
        if expanded not in seen:
            seen.add(expanded)
            result.append(expanded)
    return result


def default_lua_log_path() -> Path:
    for path in candidate_lua_log_paths():
        if path.exists():
            return path
    return candidate_lua_log_paths()[0]


def read_app_options(path: Path | None = None) -> dict[str, str]:
    options_path = path or app_options_path()
    values: dict[str, str] = {}
    if not options_path.exists():
        return values
    with options_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                values[parts[0]] = parts[1]
    return values


def bridge_mod_status(db_path: Path | None = None) -> dict[str, Any]:
    path = db_path or mods_sqlite_path()
    installed_path = mods_dir() / "Civ6AgentBridge"
    status: dict[str, Any] = {
        "installed": installed_path.exists(),
        "installed_path": str(installed_path),
        "sqlite_path": str(path),
        "sqlite_exists": path.exists(),
        "scanned": False,
        "enabled_in_selected_group": False,
    }
    if not path.exists():
        return status
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        mod_rows = connection.execute(
            """
            select m.ModRowId, m.ModId, m.Version, s.Path
            from Mods m
            join ScannedFiles s on s.ScannedFileRowId = m.ScannedFileRowId
            where lower(m.ModId) = lower(?)
               or s.Path like '%Civ6AgentBridge%'
            """,
            (BRIDGE_MOD_ID,),
        ).fetchall()
        if not mod_rows:
            return status
        row = mod_rows[-1]
        status.update(
            {
                "scanned": True,
                "mod_row_id": row["ModRowId"],
                "mod_id": row["ModId"],
                "version": row["Version"],
                "scanned_path": row["Path"],
            }
        )
        enabled = connection.execute(
            """
            select 1
            from ModGroupItems i
            join ModGroups g on g.ModGroupRowId = i.ModGroupRowId
            where i.ModRowId = ?
              and g.Selected = 1
              and i.Disabled = 0
            limit 1
            """,
            (row["ModRowId"],),
        ).fetchone()
        status["enabled_in_selected_group"] = enabled is not None
        return status
    finally:
        connection.close()


def enable_bridge_mod(db_path: Path | None = None) -> dict[str, Any]:
    path = db_path or mods_sqlite_path()
    if not path.exists():
        return {"ok": False, "error": f"Mods.sqlite not found: {path}", "status": bridge_mod_status(path)}
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            select m.ModRowId, m.ModId, m.Version, s.Path
            from Mods m
            join ScannedFiles s on s.ScannedFileRowId = m.ScannedFileRowId
            where lower(m.ModId) = lower(?)
               or s.Path like '%Civ6AgentBridge%'
            order by m.ModRowId desc
            limit 1
            """,
            (BRIDGE_MOD_ID,),
        ).fetchone()
        if row is None:
            return {
                "ok": False,
                "error": "Civ6AgentBridge has not been scanned by Civ 6 yet",
                "status": bridge_mod_status(path),
            }
        group = connection.execute(
            """
            select ModGroupRowId, Name
            from ModGroups
            where Selected = 1
            order by ModGroupRowId
            limit 1
            """
        ).fetchone()
        if group is None:
            connection.execute(
                """
                insert into ModGroups(Name, CanDelete, Selected, SortIndex)
                values('LOC_MODS_GROUP_DEFAULT_NAME', 0, 1, 100)
                """
            )
            group_id = int(connection.execute("select last_insert_rowid()").fetchone()[0])
            group_name = "LOC_MODS_GROUP_DEFAULT_NAME"
        else:
            group_id = int(group["ModGroupRowId"])
            group_name = group["Name"]
        connection.execute(
            """
            insert into ModGroupItems(ModGroupRowId, ModRowId, Disabled)
            values(?, ?, 0)
            on conflict(ModGroupRowId, ModRowId)
            do update set Disabled = 0
            """,
            (group_id, int(row["ModRowId"])),
        )
        connection.commit()
        return {
            "ok": True,
            "mod_row_id": int(row["ModRowId"]),
            "mod_id": row["ModId"],
            "mod_path": row["Path"],
            "selected_group_id": group_id,
            "selected_group_name": group_name,
            "status": bridge_mod_status(path),
        }
    finally:
        connection.close()


def bridge_log_markers(path: Path | None = None) -> dict[str, Any]:
    log_path = path or default_lua_log_path()
    status: dict[str, Any] = {
        "path": str(log_path),
        "exists": log_path.exists(),
        "bridge_ready": False,
        "state_records": 0,
        "command_records": 0,
        "latest_state_line": None,
        "latest_command_line": None,
    }
    if not log_path.exists():
        return status
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            if BRIDGE_READY_MARKER in line:
                status["bridge_ready"] = True
            if STATE_PREFIX in line:
                status["state_records"] += 1
                status["latest_state_line"] = line_no
            if COMMAND_PREFIX in line:
                status["command_records"] += 1
                status["latest_command_line"] = line_no
    return status


def civ6_status() -> dict[str, Any]:
    app_path = steam_app_path()
    install_root = steam_install_root()
    root = support_root()
    return {
        "app_path": str(app_path) if app_path.exists() else None,
        "steam_install_root": str(install_root) if install_root.exists() else None,
        "steam_library_roots": [str(path) for path in steam_library_roots()],
        "steam_install_candidates": [
            {
                "path": str(path),
                "exists": path.exists(),
                "flavor": steam_install_flavor_for_root(path),
            }
            for path in steam_install_candidates()
        ],
        "steam_downloading_candidates": steam_download_status(),
        "steam_appmanifest": read_steam_appmanifest(),
        "steam_install_flavor": steam_install_flavor(),
        "support_root": str(root) if root.exists() else None,
        "mods_dir": str(mods_dir()) if mods_dir().exists() else None,
        "mod": bridge_mod_status(),
        "options": read_app_options(),
        "log": bridge_log_markers(),
    }


def iter_prefixed_json_records(path: Path, prefix: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        raise FileNotFoundError(f"Civ 6 Lua log not found: {path}")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            marker = line.find(prefix)
            if marker < 0:
                continue
            payload = line[marker + len(prefix):].strip()
            try:
                record = json.loads(payload)
            except json.JSONDecodeError as exc:
                records.append(
                    {
                        "schema": "civ6-agent-parse-error-v0",
                        "line": line_no,
                        "error": str(exc),
                        "raw": payload,
                    }
                )
                continue
            if isinstance(record, dict):
                record.setdefault("_source", {})
                record["_source"].update({"path": str(path), "line": line_no})
                records.append(record)
    return records


def iter_state_records(path: Path) -> list[dict[str, Any]]:
    return iter_prefixed_json_records(path, STATE_PREFIX)


def iter_command_records(path: Path) -> list[dict[str, Any]]:
    return iter_prefixed_json_records(path, COMMAND_PREFIX)


def latest_state(path: Path | None = None) -> dict[str, Any]:
    log_path = path or default_lua_log_path()
    records = [
        record for record in iter_state_records(log_path)
        if record.get("schema") == "civ6-agent-state-v0"
    ]
    if not records:
        raise RuntimeError(f"no CIV6_AGENT_STATE records found in {log_path}")
    return records[-1]


def latest_command_result(path: Path | None = None) -> dict[str, Any]:
    log_path = path or default_lua_log_path()
    records = [
        record for record in iter_command_records(log_path)
        if record.get("schema") == "civ6-agent-command-result-v0"
    ]
    if not records:
        raise RuntimeError(f"no CIV6_AGENT_COMMAND records found in {log_path}")
    return records[-1]


def wait_for_state(
    path: Path | None = None,
    *,
    timeout: float = 300.0,
    interval: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return latest_state(path)
        except Exception as exc:  # noqa: BLE001 - polling should report the last bridge/log failure.
            last_error = exc
            time.sleep(interval)
    raise RuntimeError(f"timed out waiting for Civ 6 bridge state: {last_error}")
