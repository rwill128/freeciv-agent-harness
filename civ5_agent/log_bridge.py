from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


STATE_PREFIX = "CIV5_AGENT_STATE\t"
COMMAND_PREFIX = "CIV5_AGENT_COMMAND\t"
BRIDGE_READY_MARKER = "CIV5_AGENT_BRIDGE_READY"
BRIDGE_MOD_ID = "35b1f59d-4c8e-4c74-95fa-2a39e1d50001"
CIV5_STEAM_APP_ID = "8930"
CIV5_INSTALL_DIR_NAME = "Sid Meier's Civilization V"


def support_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "Sid Meier's Civilization 5"


def mods_dir() -> Path:
    return support_root() / "MODS"


def config_ini_path() -> Path:
    return support_root() / "config.ini"


def default_lua_log_path() -> Path:
    return support_root() / "Logs" / "Lua.log"


def candidate_lua_log_paths() -> list[Path]:
    paths = []
    env_path = os.environ.get("CIV5_LUA_LOG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(default_lua_log_path())
    seen: set[Path] = set()
    result = []
    for path in paths:
        expanded = path.expanduser()
        if expanded not in seen:
            seen.add(expanded)
            result.append(expanded)
    return result


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
    env_root = os.environ.get("CIV5_STEAM_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    for library_root in steam_library_roots():
        candidates.append(library_root / "steamapps" / "common" / CIV5_INSTALL_DIR_NAME)
    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def steam_appmanifest_candidates() -> list[Path]:
    return [
        library_root / "steamapps" / f"appmanifest_{CIV5_STEAM_APP_ID}.acf"
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
        if (candidate / "Civilization V.app").exists():
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def steam_app_path() -> Path:
    return steam_install_root() / "Civilization V.app"


def steam_install_flavor_for_root(root: Path) -> str:
    if (root / "Civilization V.app").exists():
        return "macos_app"
    if root.exists():
        return "unknown_present"
    return "not_found"


def steam_install_flavor() -> str:
    return steam_install_flavor_for_root(steam_install_root())


def read_config_ini(path: Path | None = None) -> dict[str, str]:
    ini_path = path or config_ini_path()
    values: dict[str, str] = {}
    if not ini_path.exists():
        return values
    with ini_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith(";") or stripped.startswith("["):
                continue
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def bridge_mod_status() -> dict[str, Any]:
    installed_path = mods_dir() / "Civ5AgentBridge"
    modinfo_path = installed_path / "Civ5AgentBridge.modinfo"
    return {
        "installed": installed_path.exists(),
        "installed_path": str(installed_path),
        "modinfo_path": str(modinfo_path),
        "modinfo_exists": modinfo_path.exists(),
    }


def log_status(path: Path | None = None) -> dict[str, Any]:
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
        for line_number, line in enumerate(handle, start=1):
            if BRIDGE_READY_MARKER in line:
                status["bridge_ready"] = True
            if line.startswith(STATE_PREFIX):
                status["state_records"] += 1
                status["latest_state_line"] = line_number
            if line.startswith(COMMAND_PREFIX):
                status["command_records"] += 1
                status["latest_command_line"] = line_number
    return status


def civ5_status() -> dict[str, Any]:
    config = read_config_ini()
    root = steam_install_root()
    return {
        "app_path": str(steam_app_path()) if steam_app_path().exists() else None,
        "steam_install_root": str(root),
        "steam_install_flavor": steam_install_flavor_for_root(root),
        "steam_install_candidates": [
            {
                "path": str(path),
                "exists": path.exists(),
                "contains_macos_app": (path / "Civilization V.app").exists(),
            }
            for path in steam_install_candidates()
        ],
        "steam_library_roots": [str(path) for path in steam_library_roots()],
        "steam_appmanifest": read_steam_appmanifest(),
        "support_root": str(support_root()),
        "mods_dir": str(mods_dir()),
        "config_ini": str(config_ini_path()),
        "config": {
            "EnableTuner": config.get("EnableTuner"),
            "EnableLuaDebugLibrary": config.get("EnableLuaDebugLibrary"),
            "MessageLog": config.get("MessageLog"),
            "Audio.Disable Sid Sounds": config.get("Disable Sid Sounds"),
            "Audio.Enable music": config.get("Enable music"),
        },
        "mod": bridge_mod_status(),
        "log": log_status(),
    }


def latest_prefixed_json(prefix: str, path: Path | None = None) -> dict[str, Any]:
    log_path = path or default_lua_log_path()
    if not log_path.exists():
        raise FileNotFoundError(f"Civ 5 Lua log not found: {log_path}")
    latest: dict[str, Any] | None = None
    last_error: Exception | None = None
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith(prefix):
                continue
            raw = line[len(prefix):].strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                latest = parsed
    if latest is None:
        if last_error:
            raise RuntimeError(f"no valid {prefix.strip()} records found: {last_error}") from last_error
        raise RuntimeError(f"no {prefix.strip()} records found in {log_path}")
    return latest


def latest_state(path: Path | None = None) -> dict[str, Any]:
    return latest_prefixed_json(STATE_PREFIX, path)


def latest_command_result(path: Path | None = None) -> dict[str, Any]:
    return latest_prefixed_json(COMMAND_PREFIX, path)


def wait_for_state(path: Path | None = None, *, timeout: float = 300.0, interval: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return latest_state(path)
        except Exception as exc:  # noqa: BLE001 - wait loop returns final concise failure.
            last_error = exc
        time.sleep(interval)
    raise RuntimeError(f"timed out waiting for Civ 5 bridge state: {last_error}")
