import time
import unittest

from briefbot.config import Config
from briefbot.store import Store
from briefbot.tracker import Tracker

ME = "UME"


def ts(offset: int) -> str:
    return f"{time.time() - 3600 + offset:.6f}"


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.config = Config(owner_user_id=ME, owner_usergroup_ids=["SGROUP"])
        self.tracker = Tracker(self.store, self.config)

    def msg(self, user, text, offset, channel="C1", channel_type="channel", thread=None, **extra):
        event = {"type": "message", "user": user, "text": text, "ts": ts(offset), "channel": channel,
                 "channel_type": channel_type, **extra}
        if thread:
            event["thread_ts"] = thread
        self.tracker.on_message(event)
        return event["ts"]

    def open_ts(self):
        return [p.ts for p in self.store.open_items(30)]

    def test_dm_is_pending_until_i_reply(self):
        a = self.msg("UALICE", "can you review?", 0, channel="D1", channel_type="im")
        self.assertEqual(self.open_ts(), [a])
        self.msg(ME, "on it", 10, channel="D1", channel_type="im")
        self.assertEqual(self.open_ts(), [])

    def test_dm_after_my_reply_is_still_pending(self):
        self.msg(ME, "hi", 0, channel="D1", channel_type="im")
        b = self.msg("UALICE", "one more thing", 10, channel="D1", channel_type="im")
        self.assertEqual(self.open_ts(), [b])

    def test_channel_chatter_is_ignored(self):
        self.msg("UBOB", "lunch?", 0)
        self.assertEqual(self.open_ts(), [])

    def test_mention_resolved_by_thread_reply(self):
        a = self.msg("UBOB", f"<@{ME}> thoughts?", 0)
        self.assertEqual(self.open_ts(), [a])
        self.msg(ME, "looks good", 10, thread=a)
        self.assertEqual(self.open_ts(), [])

    def test_usergroup_mention_counts(self):
        a = self.msg("UBOB", "<!subteam^SGROUP|@platform> please check", 0)
        self.assertEqual(self.open_ts(), [a])

    def test_top_level_channel_post_only_resolves_if_it_mentions_the_asker(self):
        a = self.msg("UBOB", f"<@{ME}> thoughts?", 0)
        self.msg(ME, "unrelated announcement", 10)
        self.assertEqual(self.open_ts(), [a])
        self.msg(ME, "<@UBOB> yes, ship it", 20)
        self.assertEqual(self.open_ts(), [])

    def test_reply_in_my_thread_is_pending(self):
        root = self.msg(ME, "proposal: move standup to 10am", 0)
        r = self.msg("UCAROL", "works for me but what about Fridays?", 10, thread=root)
        self.assertEqual(self.open_ts(), [r])
        self.msg(ME, "Fridays stay at 9", 20, thread=root)
        self.assertEqual(self.open_ts(), [])

    def test_reaction_resolves(self):
        a = self.msg("UALICE", "FYI deploy at 3", 0, channel="D1", channel_type="im")
        self.tracker.on_reaction({"user": ME, "item": {"type": "message", "channel": "D1", "ts": a}})
        self.assertEqual(self.open_ts(), [])

    def test_someone_elses_reaction_does_not_resolve(self):
        a = self.msg("UALICE", "FYI", 0, channel="D1", channel_type="im")
        self.tracker.on_reaction({"user": "UBOB", "item": {"type": "message", "channel": "D1", "ts": a}})
        self.assertEqual(self.open_ts(), [a])

    def test_bot_messages_ignored_by_default(self):
        self.tracker.on_message({"bot_id": "B1", "text": f"<@{ME}> build failed", "ts": ts(0),
                                 "channel": "C1", "channel_type": "channel"})
        self.assertEqual(self.open_ts(), [])

    def test_deleted_message_is_cleared(self):
        a = self.msg("UALICE", "oops", 0, channel="D1", channel_type="im")
        self.tracker.on_message({"subtype": "message_deleted", "channel": "D1", "deleted_ts": a,
                                 "ts": ts(5), "previous_message": {"ts": a}})
        self.assertEqual(self.open_ts(), [])

    def test_edits_and_joins_are_ignored(self):
        self.tracker.on_message({"subtype": "channel_join", "user": "UBOB", "ts": ts(0), "channel": "D1",
                                 "channel_type": "im", "text": "joined"})
        self.assertEqual(self.open_ts(), [])


if __name__ == "__main__":
    unittest.main()
