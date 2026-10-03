from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

import httpx
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import Image, Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import LLMResponse, ProviderType, TokenUsage
from astrbot.core.provider.provider import Provider
from astrbot.core.provider.register import register_provider_adapter

try:
    from .chat_tools import ChatTurn, build_chat_body, parse_bridge_completion
    from .settings import bind_host, chat_url, health_url, load_settings, local_target, save_plugin_settings
except ImportError:
    from chat_tools import ChatTurn, build_chat_body, parse_bridge_completion
    from settings import bind_host, chat_url, health_url, load_settings, local_target, save_plugin_settings


def _bridge_command(settings: dict[str, str]) -> list[str]:
    parsed = urlparse(settings["api_base"])
    cli = os.path.join(settings["repo_path"], "src", "bridge", "cli.ts")
    args = [
        cli,
        "--host", bind_host(settings),
        "--port", str(parsed.port or 18765),
        "--accounts", settings["accounts_path"],
        "--token", settings["token"],
    ]
    if shutil.which("npx"):
        return ["npx", "tsx", *args]
    return ["bun", *args]


async def _health(settings: dict[str, str]) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            response = await client.get(health_url(settings["api_base"]))
        if response.status_code != 200:
            return None
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def ensure_bridge(settings: dict[str, str]) -> None:
    health = await _health(settings)
    if health and health.get("ok") is True:
        if settings["proxy"] and health.get("proxy") is not True:
            raise RuntimeError(
                "bridge is already running without the configured proxy; stop it and start it with --proxy"
            )
        return
    if not local_target(settings["api_base"]):
        raise RuntimeError(f"bridge is not reachable at {settings['api_base']}")
    if not settings["repo_path"]:
        raise RuntimeError(
            "bridge is not running; set repo_path or start it with npm run bridge -- --proxy <http-proxy>"
        )
    env = os.environ.copy()
    if settings["proxy"]:
        env["ANTIGRAVITY_PROXY"] = settings["proxy"]
    await asyncio.create_subprocess_exec(
        *_bridge_command(settings),
        cwd=settings["repo_path"],
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    for _ in range(30):
        health = await _health(settings)
        if health and health.get("ok") is True:
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("antigravity bridge did not start")


def _session_key(session_id: str | None, kwargs: dict[str, Any]) -> str:
    candidates = [
        session_id,
        kwargs.get("conversation_id"),
        kwargs.get("umo"),
        kwargs.get("unified_msg_origin"),
    ]
    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()
    return "default"


def bridge_error_text(response: httpx.Response) -> str:
    body = response.text[:400]
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return body
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str) and error["message"]:
            return error["message"]
    return body


def response_from_parsed(parsed: Any) -> LLMResponse:
    if parsed.finish_reason == "content_filter" or parsed.safety_message:
        raise Exception(parsed.safety_message or "The model output failed Gemini platform safety checks.")
    usage = TokenUsage(**parsed.usage) if parsed.usage else None
    components: list[Any] = []
    if parsed.completion_text:
        components.append(Plain(parsed.completion_text))
    for image in parsed.images or []:
        components.append(Image.fromBytes(base64.b64decode(image["data"])))
    chain = MessageChain(components) if components else None
    return LLMResponse(
        role=parsed.role,
        completion_text=parsed.completion_text,
        result_chain=chain,
        tools_call_args=parsed.tools_call_args or [],
        tools_call_name=parsed.tools_call_name or [],
        tools_call_ids=parsed.tools_call_ids or [],
        tools_call_extra_content=parsed.tools_call_extra_content,
        reasoning_content=parsed.reasoning_content,
        reasoning_signature=parsed.reasoning_signature,
        usage=usage,
    )


async def _post_chat(config: dict[str, Any], body: dict[str, Any], session_key: str) -> dict[str, Any]:
    settings = load_settings(config)
    await ensure_bridge(settings)
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        response = await client.post(
            chat_url(settings["api_base"]),
            headers={
                "Authorization": f"Bearer {settings['token']}",
                "x-session-id": session_key,
            },
            json={**body, "user": session_key},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise RuntimeError(bridge_error_text(error.response)) from error
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("bridge returned a non-object completion")
    return payload


@register_provider_adapter(
    "antigravity",
    "Gemini via the local Antigravity account pool",
    provider_type=ProviderType.CHAT_COMPLETION,
    provider_display_name="Antigravity Gemini Pool",
    default_config_tmpl={
        "type": "antigravity",
        "enable": False,
        "id": "antigravity",
        "key": ["local"],
        "api_base": "http://127.0.0.1:18765/v1",
        "proxy": "",
        "bridge_bind": "127.0.0.1",
        "accounts_path": "~/.config/opencode/antigravity-accounts.json",
        "repo_path": "",
        "model": "gemini-3.8-flash",
    },
)
class AntigravityProvider(Provider):
    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)
        self.model_name = str(provider_config.get("model") or "gemini-3.8-flash")
        self._key = "local"

    def get_current_key(self) -> str:
        return self._key

    def set_key(self, key: str) -> None:
        self._key = key

    async def get_models(self) -> list[str]:
        return ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.1-pro"]

    async def text_chat(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        func_tool: Any = None,
        contexts: list[Any] | None = None,
        system_prompt: str | None = None,
        tool_calls_result: Any = None,
        model: str | None = None,
        extra_user_content_parts: list[Any] | None = None,
        tool_choice: str = "auto",
        request_max_retries: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        del request_max_retries
        payload = await _post_chat(
            self.provider_config,
            build_chat_body(ChatTurn(
                model=model or self.get_model() or "gemini-3.8-flash",
                prompt=prompt,
                contexts=tuple(contexts or ()),
                system_prompt=system_prompt,
                func_tool=func_tool,
                tool_calls_result=tool_calls_result,
                tool_choice=tool_choice,
                image_urls=tuple(image_urls or ()),
                audio_urls=tuple(audio_urls or ()),
                extra_user_content_parts=tuple(extra_user_content_parts or ()),
            )),
            _session_key(session_id, kwargs),
        )
        return response_from_parsed(parse_bridge_completion(payload))

    async def text_chat_stream(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        func_tool: Any = None,
        contexts: list[Any] | None = None,
        system_prompt: str | None = None,
        tool_calls_result: Any = None,
        model: str | None = None,
        tool_choice: str = "auto",
        request_max_retries: int | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMResponse, None]:
        result = await self.text_chat(
            prompt=prompt,
            session_id=session_id,
            image_urls=image_urls,
            audio_urls=audio_urls,
            func_tool=func_tool,
            contexts=contexts,
            system_prompt=system_prompt,
            tool_calls_result=tool_calls_result,
            model=model,
            tool_choice=tool_choice,
            request_max_retries=request_max_retries,
            **kwargs,
        )
        yield LLMResponse(
            role=result.role,
            completion_text=result.completion_text,
            reasoning_content=result.reasoning_content,
            is_chunk=True,
        )
        yield LLMResponse(
            role=result.role,
            completion_text=result.completion_text,
            result_chain=result.result_chain,
            tools_call_args=result.tools_call_args,
            tools_call_name=result.tools_call_name,
            tools_call_ids=result.tools_call_ids,
            tools_call_extra_content=result.tools_call_extra_content,
            reasoning_content=result.reasoning_content,
            reasoning_signature=result.reasoning_signature,
            usage=result.usage,
            is_chunk=False,
        )


@register(
    "astrbot_plugin_antigravity",
    "wedreamer",
    "Proxy AstrBot chat to the local Antigravity Gemini pool bridge",
    "0.1.1",
)
class AntigravityPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        save_plugin_settings(self.config)
