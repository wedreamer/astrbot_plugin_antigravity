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


if __name__ == "__main__":
    unittest.main()
