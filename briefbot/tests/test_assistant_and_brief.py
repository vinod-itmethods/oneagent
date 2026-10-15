import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from briefbot.assistant import Assistant
from briefbot.brief import BriefBuilder
from briefbot.config import Config
from briefbot.store import Store


class FakeReader:
    tz = __import__("zoneinfo").ZoneInfo("UTC")

    def __init__(self):
        self.searches = []

    def search(self, query, count=20):
        self.searches.append(query)
        return [{"ts": "1760000000.0", "user": "UALICE", "text": "Budget is approved", "channel": {"id": "C1"},
                 "permalink": "https://x.slack.com/p1"}]

    def format_message(self, m, channel=None):
        return f"alice: {m['text']} {m.get('permalink', '')}"

    def user_name(self, u):
        return {"UALICE": "Alice"}.get(u, u)

    def channel_label(self, c):
        return "#finance"

    def permalink(self, c, ts):
        return "https://x.slack.com/p"

    def resolve_channel(self, name):
        return None


def response(content, stop_reason):
    return NS(content=content, stop_reason=stop_reason)


class AssistantTest(unittest.TestCase):
    def setUp(self):
        self.config = Config(owner_user_id="UME", claude_provider="anthropic")
        self.store = Store(":memory:")
        self.reader = FakeReader()
        with mock.patch("briefbot.assistant.anthropic.Anthropic"):
            self.assistant = Assistant(self.config, self.reader, self.store)
        self.create = self.assistant.client.beta.messages.create

    def test_tool_loop_runs_search_then_answers(self):
        self.create.side_effect = [
            response([NS(type="tool_use", id="t1", name="search_messages", input={"query": "budget"})], "tool_use"),
            response([NS(type="text", text="*Alice*: the budget is approved.")], "end_turn"),
        ]
        answer = self.assistant.answer("is the budget approved?")
        self.assertEqual(answer, "*Alice*: the budget is approved.")
        self.assertEqual(self.reader.searches, ["budget"])
        second_call = self.create.call_args_list[1].kwargs
        tool_result = second_call["messages"][2]["content"][0]
        self.assertEqual(tool_result["tool_use_id"], "t1")
        self.assertIn("Budget is approved", tool_result["content"])
        self.assertEqual(second_call["fallbacks"], "default")

    def test_tool_errors_are_reported_to_claude(self):
        self.create.side_effect = [
            response([NS(type="tool_use", id="t1", name="read_channel", input={"channel": "#nope"})], "tool_use"),
            response([NS(type="text", text="No such channel.")], "end_turn"),
        ]
        self.assertEqual(self.assistant.answer("what's in #nope"), "No such channel.")
        result = self.create.call_args_list[1].kwargs["messages"][2]["content"][0]
        self.assertIn("No channel named #nope", result["content"])

    def test_refusal(self):
        self.create.return_value = response([], "refusal")
        self.assertIn("can't help", self.assistant.answer("..."))

    def test_brief_lists_items_with_buttons(self):
        now = time.time()
        self.store.add_pending("D1", f"{now - 7200:.6f}", None, "UALICE", "Can you sign off the budget?", "dm")
        self.store.add_pending("C1", f"{now - 600:.6f}", None, "UBOB", "<@UME> review pls", "mention")
        self.create.return_value = response([NS(type="text", text="*Needs you first*\n• Alice: budget sign-off")], "end_turn")

        text, blocks = BriefBuilder(self.config, self.store, self.reader, self.assistant).build()
        self.assertIn("2 message(s)", text)
        items = [b for b in blocks if b.get("block_id", "").startswith("item_")]
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["text"]["text"].startswith("*1.* *UBOB*"))  # newest first
        self.assertEqual(items[0]["accessory"]["action_id"], "mark_handled")
        self.assertEqual(set(self.store.get("last_brief")), {"1", "2"})

    def test_empty_brief(self):
        text, blocks = BriefBuilder(self.config, self.store, self.reader, self.assistant).build()
        self.assertIn("caught up", blocks[0]["text"]["text"])
        self.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
