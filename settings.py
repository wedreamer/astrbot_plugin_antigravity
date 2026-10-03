from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

DEFAULT_API_BASE = "http://127.0.0.1:18765/v1"
DEFAULT_ACCOUNTS = "~/.config/opencode/antigravity-accounts.json"
BRIDGE_FILE = os.path.expanduser("~/.config/opencode/antigravity-bridge.json")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list) and value:
        return text_value(value[0])
    return ""


def first_text(*values: Any, default: str = "") -> str:
    for value in values:
        text = text_value(value)
        if text:
            return text
    return default


def read_bridge_file(path: str = BRIDGE_FILE) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_plugin_settings(config: dict[str, Any] | None, path: str = BRIDGE_FILE) -> None:
    if not config:
        return
    incoming = {
        key: text_value(config.get(key))
        for key in ("api_base", "bridge_url", "proxy", "outbound_proxy", "accounts_path", "repo_path", "bridge_bind", "key")
        if text_value(config.get(key))
    }
    if not incoming:
        return
    current = read_bridge_file(path)
    current.update(incoming)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_settings(
    provider_config: dict[str, Any] | None,
    file_cfg: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    config = provider_config or {}
    stored = file_cfg if file_cfg is not None else read_bridge_file()
    environment = env if env is not None else os.environ
    api_base = first_text(
        config.get("api_base"),
        config.get("bridge_url"),
        environment.get("ANTIGRAVITY_BRIDGE_URL"),
        stored.get("api_base"),
        stored.get("bridge_url"),
        default=DEFAULT_API_BASE,
    ).rstrip("/")
    return {
        "api_base": api_base,
        "proxy": first_text(
            config.get("proxy"),
            config.get("outbound_proxy"),
            environment.get("ANTIGRAVITY_PROXY"),
            stored.get("proxy"),
            stored.get("outbound_proxy"),
        ),
        "accounts_path": os.path.expanduser(first_text(
            config.get("accounts_path"),
            environment.get("ANTIGRAVITY_ACCOUNTS"),
            stored.get("accounts_path"),
            default=DEFAULT_ACCOUNTS,
        )),
        "repo_path": first_text(
            config.get("repo_path"),
            environment.get("ANTIGRAVITY_REPO"),
            stored.get("repo_path"),
        ),
        "bridge_bind": first_text(
            config.get("bridge_bind"),
            environment.get("ANTIGRAVITY_BIND"),
            stored.get("bridge_bind"),
        ),
        "token": first_text(config.get("key"), stored.get("key"), default="local"),
    }


def chat_url(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def health_url(api_base: str) -> str:
    parsed = urlparse(api_base)
    return f"{parsed.scheme}://{parsed.netloc}/health"


def local_target(api_base: str) -> bool:
    return urlparse(api_base).hostname in LOCAL_HOSTS


def bind_host(settings: dict[str, str]) -> str:
    if settings["bridge_bind"]:
        return settings["bridge_bind"]
    if local_target(settings["api_base"]):
        return "127.0.0.1"
    return "0.0.0.0"
