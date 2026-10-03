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


@dataclass(frozen=True, slots=True)
class ParsedCompletion:
    role: str
    completion_text: str
    tools_call_name: list[str] | None = None
    tools_call_ids: list[str] | None = None
    tools_call_args: list[dict[str, Any]] | None = None


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
    if not calls:
        return ParsedCompletion(role="assistant", completion_text=text)
    return ParsedCompletion(
        role="tool",
        completion_text=text,
        tools_call_name=[name for name, _, _ in calls],
        tools_call_ids=[call_id for _, call_id, _ in calls],
        tools_call_args=[arguments for _, _, arguments in calls],
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
    if turn.prompt:
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
    if role == "tool" or tool_calls is not None:
        if "content" in record:
            message["content"] = record["content"]
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
    else:
        message["content"] = string_content(record.get("content"))
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
    for key in ("content", "tool_calls", "tool_call_id", "name"):
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
