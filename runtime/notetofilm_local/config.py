"""Company routes are explicit configuration, never inferred from model names."""
from __future__ import annotations

import copy
import json
import os
import re
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from .errors import NTFError


def model_catalog() -> dict:
    return json.loads(files("notetofilm_local").joinpath("data/models.json").read_text(encoding="utf-8"))


def default_config() -> dict:
    routes = {}
    for item in model_catalog()["models"]:
        routes[item["route_id"]] = {
            "model": item["id"], "modality": item["modality"],
            "connection": "company", "adapter": None,
            "capabilities": {"status": "unknown", "modes": {}},
        }
    return {
        "schema_version": 1,
        "connections": {"company": {
            "base_url_env": "NTF_COMPANY_API_BASE_URL",
            "auth": {"type": "unconfirmed", "env": "NTF_COMPANY_API_KEY"},
        }},
        "routes": routes,
        "defaults": {"image_route": "company-image-2", "video_route": "company-seedance-2-0"},
    }


def _read(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError:
                raise NTFError("config_format", "YAML configuration requires PyYAML; JSON needs no extra dependency.") from None
            data = yaml.safe_load(text)
        elif path.suffix.lower() == ".toml":
            import tomllib
            data = tomllib.loads(text)
        else:
            data = json.loads(text)
    except NTFError:
        raise
    except (OSError, ValueError) as exc:
        raise NTFError("config_invalid", "Cannot read the configuration file.", {"file": str(path), "reason": type(exc).__name__}) from None
    if not isinstance(data, dict):
        raise NTFError("config_invalid", "Configuration must be an object.")
    return data


def _reject_inline_credentials(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"api_key", "token", "password", "secret", "authorization", "x-goog-api-key", "headers"}:
                raise NTFError("config_credentials", "Use auth.env/header_envs for credentials; do not store credential values or literal headers in configuration.")
            _reject_inline_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _reject_inline_credentials(item)


def load_config(path: str | Path | None = None) -> dict:
    selected = path or os.environ.get("NTF_CONFIG")
    if not selected:
        return default_config()
    source = Path(selected).expanduser().resolve()
    config = _read(source)
    if config.get("schema_version", 1) != 1:
        raise NTFError("config_version", "Unsupported configuration schema_version.")
    _reject_inline_credentials(config)
    if not isinstance(config.get("routes"), dict) or not isinstance(config.get("connections"), dict):
        raise NTFError("config_invalid", "Configuration requires routes and connections objects.")
    for route in config["routes"].values():
        if not isinstance(route, dict):
            raise NTFError("config_invalid", "Each route must be an object.")
        profile = route.get("capabilities", route.get("capability_profile"))
        if isinstance(profile, str):
            route["capabilities"] = _read((source.parent / profile).resolve())
    return config


@contextmanager
def connection_environment(config, source=None):
    """Bind external connection values for one operation, without copying secrets."""
    if source is None:
        yield config
        return
    external = _read(Path(source).expanduser().resolve()).get("connections")
    if not isinstance(external, dict):
        raise NTFError("connections_format", "The connections file requires a connections object.")
    bound = copy.deepcopy(config)
    updates, matched = {}, 0
    for name, connection in bound["connections"].items():
        entry = external.get(name)
        if entry is None:
            continue
        if not isinstance(entry, dict):
            raise NTFError("connections_format", "Each external connection must be an object.")
        matched += 1
        if entry.get("base_url"):
            base = entry["base_url"]
            if not isinstance(base, str):
                raise NTFError("connections_format", "Connection base_url must be an HTTP(S) address.")
            parsed = urlsplit(base)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise NTFError("connections_format", "Connection base_url must not contain embedded credentials or a query.")
            connection["base_url"] = base.rstrip("/")
        credentials = entry.get("credentials", {})
        if not isinstance(credentials, dict):
            raise NTFError("connections_format", "Connection credentials must be an object.")
        key = credentials.get("api_key")
        if key is not None:
            env = connection.get("auth", {}).get("env")
            if not isinstance(env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env) or env in {"HOME", "home", "CODEX_HOME", "PATH", "SHELL", "USER", "PYTHONPATH"}:
                raise NTFError("connections_binding", "Declare a dedicated auth.env in the public route configuration before binding an external credential.")
            if not isinstance(key, str) or not key or "\n" in key or "\r" in key:
                raise NTFError("connections_format", "External api_key must be a nonempty single-line string.")
            updates[env] = key
    if not matched:
        raise NTFError("connections_binding", "No connection IDs match; select the route configuration with --config. Model IDs and protocol paths stay in that configuration.")
    previous = {name: os.environ.get(name) for name in updates}
    try:
        os.environ.update(updates)
        yield bound
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def list_routes(config: dict) -> list:
    result = []
    for route_id, route in config.get("routes", {}).items():
        cap = route.get("capabilities", {})
        result.append({
            "id": route_id, "model": route.get("model", route.get("request_model")),
            "modality": route.get("modality"), "adapter": route.get("adapter", route.get("protocol_adapter")),
            "connection": route.get("connection"), "capability_status": cap.get("status", "unknown") if isinstance(cap, dict) else "unknown",
            "modes": cap.get("modes", {}) if isinstance(cap, dict) else {},
            "connectivity": "not_tested",
        })
    return result


def resolve_route(config: dict, route_id: str | None, modality: str) -> dict:
    route_id = route_id or config.get("defaults", {}).get(f"{modality}_route")
    raw = config.get("routes", {}).get(route_id)
    if not isinstance(raw, dict):
        raise NTFError("route_missing", "Select a configured company route.", {"route": route_id, "modality": modality})
    route = copy.deepcopy(raw)
    if route.get("modality") != modality:
        raise NTFError("route_modality", "The selected route has a different modality.", {"route": route_id, "expected": modality})
    conn = route.get("connection")
    if isinstance(conn, str):
        if not isinstance(config.get("connections", {}).get(conn), dict):
            raise NTFError("connection_missing", "The route's company connection is not configured.", {"route": route_id})
        route["connection_id"] = conn
        conn = copy.deepcopy(config["connections"][conn])
    elif isinstance(conn, dict):
        conn = copy.deepcopy(conn)
    else:
        raise NTFError("connection_missing", "The route requires an explicit company connection.")
    base = conn.get("base_url") or os.environ.get(conn.get("base_url_env", ""))
    if base:
        parsed = urlsplit(base)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise NTFError("connection_invalid", "Company base URL must be an HTTP(S) URL without embedded credentials, query or fragment.")
        # Pin the non-secret connection address in the route snapshot used for resume.
        conn["base_url"] = base.rstrip("/")
    route.update({"id": route_id, "connection": conn})
    route["adapter"] = route.get("adapter", route.get("protocol_adapter"))
    model = route.get("model", route.get("request_model"))
    if route.get("request_model_env"):
        model = os.environ.get(route["request_model_env"])
    if not isinstance(model, str) or not model:
        raise NTFError("model_missing", "Configure the exact model/deployment identifier accepted by the company route.")
    route["model"] = model
    route.setdefault("capabilities", {"status": "unknown", "modes": {}})
    _reject_inline_credentials(route)
    return route
