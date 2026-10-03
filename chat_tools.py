from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChatTurn:
    model: str
    prompt: str | None = None
    contexts: tuple[Any, ...] = ()
    system_prompt: str | None = None
    func_tool: Any = None
    tool_calls_result: Any = None
    tool_choice: str = "auto"
    image_urls: tuple[str, ...] = ()
    audio_urls: tuple[str, ...] = ()
    extra_user_content_parts: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedCompletion:
    role: str
    completion_text: str
    tools_call_name: list[str] | None = None
    tools_call_ids: list[str] | None = None
    tools_call_args: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    reasoning_content: str | None = None
    reasoning_signature: str | None = None
    tools_call_extra_content: dict[str, Any] | None = None
    images: list[dict[str, str]] | None = None
    finish_reason: str | None = None
    safety_message: str | None = None


def build_chat_body(turn: ChatTurn) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": turn.model,
        "messages": posted_messages(turn),
    }
    tools = openai_tools(turn.func_tool)
    if tools:
        body["tools"] = tools
        body["tool_choice"] = turn.tool_choice
    return body


def parse_bridge_completion(payload: dict[str, Any]) -> ParsedCompletion:
    message = choice_message(payload)
    text = message_text(message.get("content"))
    calls = parsed_tool_calls(message.get("tool_calls"))
    extra = extra_content_by_id(message.get("tool_calls"))
    reasoning = message.get("reasoning_content")
    signature = payload.get("antigravity_reasoning_signature")
    if not isinstance(signature, str) or not signature:
        signature = last_signature(extra)
    common = {
        "usage": parse_usage(payload),
        "reasoning_content": reasoning if isinstance(reasoning, str) and reasoning else None,
        "reasoning_signature": signature,
        "tools_call_extra_content": extra or None,
        "images": parse_images(payload),
        "finish_reason": finish_reason(payload),
        "safety_message": safety_message(payload),
    }
    if not calls:
        return ParsedCompletion(role="assistant", completion_text=text, **common)
    return ParsedCompletion(
        role="tool",
        completion_text=text,
        tools_call_name=[name for name, _, _ in calls],
        tools_call_ids=[call_id for _, call_id, _ in calls],
        tools_call_args=[arguments for _, _, arguments in calls],
        **common,
    )


def openai_tools(func_tool: Any) -> list[dict[str, Any]]:
    if func_tool is None:
        return []
    for method_name in ("openai_schema", "get_func_desc_openai_style"):
        method = getattr(func_tool, method_name, None)
        if callable(method):
            return tools_from_schema(method())
    return tools_from_duck(func_tool)


def posted_messages(turn: ChatTurn) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if turn.system_prompt:
        messages.append({"role": "system", "content": turn.system_prompt})
    for item in turn.contexts:
        message = context_message(item)
        if message is not None:
            messages.append(message)
    append_tool_results(messages, turn.tool_calls_result)
    media = user_media(turn)
    if media is not None:
        messages.append({"role": "user", "content": media})
    elif turn.prompt:
        messages.append({"role": "user", "content": turn.prompt})
    return messages


def tools_from_schema(produced: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for item in sequence(produced):
        tool = openai_tool(item)
        if tool is not None:
            tools.append(tool)
    return tools


def tools_from_duck(func_tool: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for item in duck_items(func_tool):
        if explicitly_inactive(item):
            continue
        tool = openai_tool(item)
        if tool is not None:
            tools.append(tool)
    return tools


def context_message(item: Any) -> dict[str, Any] | None:
    record = as_record(item)
    if record is None:
        return None
    role = record.get("role")
    if not isinstance(role, str):
        return None
    tool_calls = record.get("tool_calls") if "tool_calls" in record else None
    message: dict[str, Any] = {"role": role}
    content = record.get("content")
    structured = isinstance(content, list)
    if role == "tool" or tool_calls is not None or structured:
        if "content" in record:
            message["content"] = content
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
    else:
        message["content"] = string_content(content)
    copy_present(message, record, "tool_call_id")
    copy_present(message, record, "name")
    return message


def append_tool_results(messages: list[dict[str, Any]], tool_calls_result: Any) -> None:
    if tool_calls_result is None:
        return
    method = getattr(tool_calls_result, "to_openai_messages", None)
    if callable(method):
        extend_messages(messages, method())
        return
    if not isinstance(tool_calls_result, list):
        return
    for item in tool_calls_result:
        item_method = getattr(item, "to_openai_messages", None)
        if callable(item_method):
            extend_messages(messages, item_method())
            continue
        if isinstance(item, dict):
            messages.append(item)


def user_media(turn: ChatTurn) -> list[dict[str, Any]] | None:
    if not turn.image_urls and not turn.audio_urls and not turn.extra_user_content_parts:
        return None
    parts: list[dict[str, Any]] = []
    if turn.prompt:
        parts.append({"type": "text", "text": turn.prompt})
    for url in turn.image_urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    for url in turn.audio_urls:
        parts.append({"type": "input_audio", "input_audio": {"url": url}})
    parts.extend(item for item in turn.extra_user_content_parts if isinstance(item, dict))
    return parts


def parse_usage(payload: dict[str, Any]) -> dict[str, int] | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    if "prompt_tokens" not in usage and "completion_tokens" not in usage:
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    prompt_tokens = prompt if isinstance(prompt, int) else 0
    completion_tokens = completion if isinstance(completion, int) else 0
    details = usage.get("prompt_tokens_details")
    cached = 0
    if isinstance(details, dict) and isinstance(details.get("cached_tokens"), int):
        cached = details["cached_tokens"]
    return {
        "input_other": prompt_tokens - cached,
        "input_cached": cached,
        "output": completion_tokens,
    }


def extra_content_by_id(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, list):
        return {}
    extra: dict[str, Any] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        call_id = item.get("id")
        content = item.get("extra_content")
        if isinstance(call_id, str) and call_id and isinstance(content, dict):
            extra[call_id] = content
    return extra


def last_signature(extra: dict[str, Any]) -> str | None:
    signature: str | None = None
    for content in extra.values():
        google = content.get("google") if isinstance(content, dict) else None
        value = google.get("thought_signature") if isinstance(google, dict) else None
        if isinstance(value, str) and value:
            signature = value
    return signature


def parse_images(payload: dict[str, Any]) -> list[dict[str, str]] | None:
    raw = payload.get("antigravity_images")
    if not isinstance(raw, list):
        return None
    images: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mime = item.get("mimeType")
        data = item.get("data")
        if isinstance(mime, str) and isinstance(data, str) and data:
            images.append({"mimeType": mime, "data": data})
    return images or None


def finish_reason(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    reason = choices[0].get("finish_reason")
    return reason if isinstance(reason, str) else None


def safety_message(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    return message if isinstance(message, str) and message else None


def choice_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, dict) else {}


def parsed_tool_calls(raw: Any) -> list[tuple[str, str, dict[str, Any]]]:
    if not isinstance(raw, list):
        return []
    calls: list[tuple[str, str, dict[str, Any]]] = []
    for item in raw:
        parsed = one_tool_call(item)
        if parsed is not None:
            calls.append(parsed)
    return calls


def one_tool_call(item: Any) -> tuple[str, str, dict[str, Any]] | None:
    if not isinstance(item, dict):
        return None
    function = item.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    call_id = item.get("id")
    return (name, call_id if isinstance(call_id, str) else "", arguments_object(function.get("arguments")))


def arguments_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def openai_tool(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict) and item.get("type") == "function" and isinstance(item.get("function"), dict):
        name = item["function"].get("name")
        if isinstance(name, str) and name:
            return item
        return None
    name = field(item, "name")
    if not isinstance(name, str) or not name:
        return None
    description = field(item, "description")
    parameters = field(item, "parameters")
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description if isinstance(description, str) else "",
            "parameters": {} if parameters is None else parameters,
        },
    }


def as_record(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        return item
    role = getattr(item, "role", None)
    if not isinstance(role, str):
        return None
    record: dict[str, Any] = {"role": role}
    for key in ("content", "tool_calls", "tool_call_id", "name", "extra_content"):
        if hasattr(item, key):
            record[key] = getattr(item, key)
    return record


def duck_items(func_tool: Any) -> list[Any]:
    if isinstance(func_tool, (str, bytes, dict)) or not hasattr(func_tool, "__iter__"):
        return []
    return list(func_tool)


def sequence(produced: Any) -> list[Any]:
    if isinstance(produced, dict):
        return [produced]
    if isinstance(produced, (list, tuple)):
        return list(produced)
    return []


def explicitly_inactive(item: Any) -> bool:
    if isinstance(item, dict):
        return item.get("active") is False
    return getattr(item, "active", None) is False


def field(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def copy_present(message: dict[str, Any], record: dict[str, Any], key: str) -> None:
    if key in record and record[key] is not None:
        message[key] = record[key]


def extend_messages(messages: list[dict[str, Any]], produced: Any) -> None:
    if isinstance(produced, list):
        messages.extend(produced)


def message_text(content: Any) -> str:
    return content if isinstance(content, str) else ""


def string_content(content: Any) -> str:
    return content if isinstance(content, str) else str(content or "")
