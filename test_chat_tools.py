from __future__ import annotations

import unittest

from chat_tools import ChatTurn, build_chat_body, parse_bridge_completion

PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


class _Tool:
    def __init__(self, name: str, active: bool = True) -> None:
        self.name = name
        self.description = "search the canon"
        self.parameters = PARAMETERS
        self.active = active


class _Result:
    def to_openai_messages(self) -> list[dict[str, object]]:
        return [{
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "cbeta_search",
            "content": "volume 1",
        }]


class ChatToolsTest(unittest.TestCase):
    def test_posts_cbeta_search_when_func_tool_is_duck_typed(self) -> None:
        body = build_chat_body(ChatTurn(
            model="gemini-3.8-flash",
            prompt="find the sutra",
            func_tool=[_Tool("cbeta_search"), _Tool("inactive_tool", active=False)],
        ))

        self.assertEqual(body["tools"][0]["function"]["name"], "cbeta_search")
        self.assertEqual(body["tools"][0]["function"]["parameters"], PARAMETERS)
        self.assertEqual([tool["function"]["name"] for tool in body["tools"]], ["cbeta_search"])
        self.assertEqual(body["tool_choice"], "auto")

    def test_maps_tool_calls_when_bridge_returns_function_calls(self) -> None:
        parsed = parse_bridge_completion({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "cbeta_search",
                            "arguments": '{"query":"heart sutra"}',
                        },
                    }],
                },
            }],
        })

        self.assertEqual(parsed.tools_call_name, ["cbeta_search"])
        self.assertEqual(parsed.tools_call_args, [{"query": "heart sutra"}])
        self.assertEqual(parsed.tools_call_ids, ["call_1"])
        self.assertEqual(parsed.role, "tool")

    def test_appends_tool_results_when_context_has_tool_role(self) -> None:
        body = build_chat_body(ChatTurn(
            model="gemini-3.8-flash",
            contexts=(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "cbeta_search", "arguments": "{}"},
                    }],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "cbeta_search",
                    "content": {"hits": 2},
                },
            ),
            tool_calls_result=[
                _Result(),
                {"role": "tool", "tool_call_id": "call_2", "content": "plain", "name": "cbeta_search"},
            ],
        ))

        messages = body["messages"]
        self.assertIsNone(messages[0]["content"])
        self.assertEqual(messages[0]["tool_calls"][0]["function"]["name"], "cbeta_search")
        self.assertEqual(messages[1]["role"], "tool")
        self.assertEqual(messages[1]["content"], {"hits": 2})
        self.assertEqual(messages[1]["tool_call_id"], "call_1")
        self.assertEqual(messages[2]["content"], "volume 1")
        self.assertEqual(messages[3], {
            "role": "tool",
            "tool_call_id": "call_2",
            "content": "plain",
            "name": "cbeta_search",
        })

    def test_returns_completion_text_when_no_tools(self) -> None:
        body = build_chat_body(ChatTurn(model="gemini-3.8-flash", prompt="hello"))
        parsed = parse_bridge_completion({
            "choices": [{"message": {"role": "assistant", "content": "still here"}}],
        })

        self.assertNotIn("tools", body)
        self.assertEqual(parsed.role, "assistant")
        self.assertEqual(parsed.completion_text, "still here")
        self.assertIsNone(parsed.tools_call_name)

    def test_uses_empty_object_when_arguments_are_invalid_json(self) -> None:
        parsed = parse_bridge_completion({
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_bad",
                        "function": {"name": "cbeta_search", "arguments": "{not-json"},
                    }],
                },
            }],
        })

        self.assertEqual(parsed.tools_call_args, [{}])
        self.assertEqual(parsed.role, "tool")

    def test_posts_schema_tools_when_openai_schema_exists(self) -> None:
        class SchemaSet:
            def openai_schema(self) -> list[dict[str, object]]:
                return [{
                    "type": "function",
                    "function": {
                        "name": "cbeta_search",
                        "description": "from schema",
                        "parameters": PARAMETERS,
                    },
                }]

            def __iter__(self):
                yield _Tool("duck_should_not_win")

        body = build_chat_body(ChatTurn(model="gemini-3.8-flash", func_tool=SchemaSet()))

        self.assertEqual(body["tools"][0]["function"]["name"], "cbeta_search")
        self.assertEqual(body["tools"][0]["function"]["parameters"], PARAMETERS)

    def test_posts_legacy_schema_when_only_func_desc_exists(self) -> None:
        class LegacySet:
            def get_func_desc_openai_style(self) -> list[dict[str, object]]:
                return [{
                    "type": "function",
                    "function": {
                        "name": "cbeta_search",
                        "description": "legacy",
                        "parameters": PARAMETERS,
                    },
                }]

        body = build_chat_body(ChatTurn(
            model="gemini-3.8-flash",
            func_tool=LegacySet(),
            tool_choice="required",
        ))

        self.assertEqual(body["tools"][0]["function"]["name"], "cbeta_search")
        self.assertEqual(body["tool_choice"], "required")

    def test_extends_messages_when_tool_calls_result_has_to_openai_messages(self) -> None:
        body = build_chat_body(ChatTurn(model="gemini-3.8-flash", tool_calls_result=_Result()))

        self.assertEqual(body["messages"], [{
            "role": "tool",
            "tool_call_id": "call_1",
            "name": "cbeta_search",
            "content": "volume 1",
        }])

    def test_maps_usage_signature_and_keeps_structured_context(self) -> None:
        parsed = parse_bridge_completion({
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 7,
                "total_tokens": 107,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
            "antigravity_reasoning_signature": "SIG",
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "why",
                    "tool_calls": [{
                        "id": "fc_1",
                        "type": "function",
                        "function": {"name": "cbeta_search", "arguments": "{}"},
                        "extra_content": {"google": {"thought_signature": "SIG"}},
                    }],
                },
            }],
        })
        self.assertEqual(parsed.usage, {"input_other": 60, "input_cached": 40, "output": 7})
        self.assertEqual(parsed.reasoning_content, "why")
        self.assertEqual(parsed.reasoning_signature, "SIG")
        self.assertEqual(parsed.tools_call_extra_content, {"fc_1": {"google": {"thought_signature": "SIG"}}})
        self.assertNotIn("why", parsed.completion_text)

        body = build_chat_body(ChatTurn(
            model="gemini-3.8-flash",
            contexts=({
                "role": "assistant",
                "content": [{"type": "think", "think": "why", "encrypted": "SIG"}],
                "tool_calls": [{
                    "id": "fc_1",
                    "extra_content": {"google": {"thought_signature": "SIG"}},
                }],
            },),
        ))
        message = body["messages"][0]
        self.assertEqual(message["content"][0]["type"], "think")
        self.assertEqual(message["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "SIG")
        self.assertNotIsInstance(message["content"], str)


class ProviderFieldTest(unittest.TestCase):
    def test_text_chat_passes_usage_and_stream_final_is_not_a_chunk(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock, patch

        from astrbot.core.provider.entities import TokenUsage
        from main import AntigravityProvider, _post_chat

        payload = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "answer", "reasoning_content": "why"},
            }],
        }
        provider = AntigravityProvider({"model": "gemini-3.8-flash"}, {})
        with patch("main._post_chat", new=AsyncMock(return_value=payload)):
            result = asyncio.run(provider.text_chat(prompt="hi"))
            chunks = asyncio.run(self._collect(provider.text_chat_stream(prompt="hi")))
        self.assertIsInstance(result.usage, TokenUsage)
        self.assertEqual(result.usage, TokenUsage(input_other=60, input_cached=40, output=7))
        self.assertEqual(chunks[-1].is_chunk, False)
        self.assertEqual(chunks[-1].usage.output, 7)
        self.assertEqual(chunks[0].completion_text, "answer")
        self.assertEqual(len([chunk.completion_text for chunk in chunks if chunk.is_chunk]), 1)

    def test_content_filter_raises_safety_sentence(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock, patch

        from main import AntigravityProvider

        payload = {
            "error": {"message": "The model output failed Gemini platform safety checks."},
            "choices": [{"finish_reason": "content_filter", "message": {"role": "assistant", "content": ""}}],
        }
        provider = AntigravityProvider({"model": "gemini-3.8-flash"}, {})
        with patch("main._post_chat", new=AsyncMock(return_value=payload)):
            with self.assertRaises(Exception) as caught:
                asyncio.run(provider.text_chat(prompt="hi"))
        self.assertIn("The model output failed Gemini platform safety checks.", str(caught.exception))

    def test_post_chat_includes_error_message_without_bearer(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock, patch

        import httpx
        from main import _post_chat

        class _Response:
            text = '{"error": {"message": "upstream status 400: Proto field is not repeating, cannot start list."}}'

            def raise_for_status(self) -> None:
                request = httpx.Request("POST", "http://127.0.0.1/v1/chat/completions")
                response = httpx.Response(400, request=request, text=self.text)
                raise httpx.HTTPStatusError("bad", request=request, response=response)

        class _Client:
            async def __aenter__(self) -> "_Client":
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, *args: object, **kwargs: object) -> _Response:
                return _Response()

        with patch("main.httpx.AsyncClient", return_value=_Client()), \
                patch("main.ensure_bridge", new=AsyncMock()), \
                patch("main.load_settings", return_value={"api_base": "http://127.0.0.1:9/v1", "token": "secret-token"}), \
                patch("main.chat_url", return_value="http://127.0.0.1:9/v1/chat/completions"):
            with self.assertRaises(RuntimeError) as caught:
                asyncio.run(_post_chat({}, {"messages": []}, "session"))
        self.assertIn("Proto field is not repeating, cannot start list.", str(caught.exception))
        self.assertNotIn("Bearer", str(caught.exception))

    async def _collect(self, stream: object) -> list[object]:
        items = []
        async for item in stream:  # type: ignore[operator]
            items.append(item)
        return items


if __name__ == "__main__":
    unittest.main()
