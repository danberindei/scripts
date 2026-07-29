"""Unit tests for the quota pacing logic in claude-hooks.

The hook script has no .py extension, so it is loaded by path.
Run with: uv run python -m unittest test_claude_check_quota
"""

import importlib.util
import os
import unittest
from importlib.machinery import SourceFileLoader

_PATH = os.path.join(os.path.dirname(__file__), "claude-hooks")
_loader = SourceFileLoader("claude_hooks", _PATH)
_spec = importlib.util.spec_from_loader("claude_hooks", _loader)
q = importlib.util.module_from_spec(_spec)
_loader.exec_module(q)

_CODEX_PATH = os.path.join(os.path.dirname(__file__), "codex-hooks")
_codex_loader = SourceFileLoader("codex_hooks", _CODEX_PATH)
_codex_spec = importlib.util.spec_from_loader("codex_hooks", _codex_loader)
c = importlib.util.module_from_spec(_codex_spec)
_codex_loader.exec_module(c)

HOUR_MS = 60 * 60 * 1000
FIVE_HOUR_MS = 5 * HOUR_MS


def window(util, reset_iso):
    return {"utilization": util, "resets_at": reset_iso}


class ParseResetMsTest(unittest.TestCase):
    def test_z_suffix(self):
        self.assertEqual(q.parse_reset_ms("1970-01-01T00:00:01Z"), 1000)

    def test_fractional_seconds(self):
        # Fractional seconds are kept; truncated to whole ms.
        self.assertEqual(q.parse_reset_ms("1970-01-01T00:00:00.250Z"), 250)

    def test_explicit_offset(self):
        # 01:00:00+01:00 == 00:00:00Z == epoch 0.
        self.assertEqual(q.parse_reset_ms("1970-01-01T01:00:00+01:00"), 0)

    def test_naive_treated_as_utc(self):
        self.assertEqual(q.parse_reset_ms("1970-01-01T00:00:01"), 1000)

    def test_unparseable(self):
        self.assertIsNone(q.parse_reset_ms("not-a-date"))
        self.assertIsNone(q.parse_reset_ms(""))
        self.assertIsNone(q.parse_reset_ms(None))


class CheckWindowTest(unittest.TestCase):
    def setUp(self):
        # "now" is a fixed epoch; reset is 4h in the future for a 5h window,
        # so 1h has elapsed (elapsed_frac = 0.2).
        self.now_ms = 1_000_000_000_000
        self.reset_iso = self._iso(self.now_ms + 4 * HOUR_MS)

    @staticmethod
    def _iso(ms):
        from datetime import datetime, timezone

        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def test_none_window_is_ok(self):
        self.assertIsNone(q.check_window("five_hour", None, self.now_ms, FIVE_HOUR_MS))

    def test_missing_fields_are_ok(self):
        self.assertIsNone(q.check_window("five_hour", {}, self.now_ms, FIVE_HOUR_MS))
        self.assertIsNone(
            q.check_window("five_hour", {"utilization": 50}, self.now_ms, FIVE_HOUR_MS)
        )

    def test_already_reset_is_ok(self):
        past = self._iso(self.now_ms - HOUR_MS)
        self.assertIsNone(q.check_window("five_hour", window(99, past), self.now_ms, FIVE_HOUR_MS))

    def test_on_pace_is_ok(self):
        # elapsed_frac = 0.2 -> expected_remaining = 80, threshold = 40.
        # remaining = 100 - 50 = 50 >= 40 -> not red.
        self.assertIsNone(
            q.check_window("five_hour", window(50, self.reset_iso), self.now_ms, FIVE_HOUR_MS)
        )

    def test_red_when_below_half_expected(self):
        # threshold = 40; utilization 70 -> remaining 30 < 40 -> red.
        msg = q.check_window("five_hour", window(70, self.reset_iso), self.now_ms, FIVE_HOUR_MS)
        self.assertIsNotNone(msg)
        self.assertIn("five_hour", msg)
        self.assertIn("30% left", msg)
        self.assertIn("expected 80%", msg)

    def test_boundary_equal_threshold_is_ok(self):
        # remaining exactly == threshold (40) is not red (strict <).
        msg = q.check_window("five_hour", window(60, self.reset_iso), self.now_ms, FIVE_HOUR_MS)
        self.assertIsNone(msg)


class RedWindowsTest(unittest.TestCase):
    def test_collects_only_red(self):
        now_ms = 1_000_000_000_000
        reset = CheckWindowTest._iso(now_ms + 4 * HOUR_MS)
        usage = {
            "five_hour": window(70, reset),  # red
            "seven_day": window(1, reset),  # fine
        }
        msgs = q.red_windows(usage, now_ms)
        self.assertEqual(len(msgs), 1)
        self.assertIn("five_hour", msgs[0])


class QuotaTemporaryPatternTest(unittest.TestCase):
    def test_matches_continue(self):
        self.assertIsNotNone(q.QUOTA_TEMPORARY_PATTERN.search("continue in 30"))

    def test_matches_snooze(self):
        self.assertIsNotNone(q.QUOTA_TEMPORARY_PATTERN.search("snooze for 1.5h"))

    def test_no_match_unrelated(self):
        self.assertIsNone(q.QUOTA_TEMPORARY_PATTERN.search("what's the weather today"))


class HandoffPromptPatternTest(unittest.TestCase):
    def test_matches_session_handoff_anywhere(self):
        self.assertIsNotNone(q.HANDOFF_PROMPT_PATTERN.search("/session-handoff"))
        self.assertIsNotNone(q.HANDOFF_PROMPT_PATTERN.search("session-handoff"))
        self.assertIsNotNone(
            q.HANDOFF_PROMPT_PATTERN.search("wrap up:\nsession-handoff\nkeep it short")
        )

    def test_does_not_match_handoff_prose(self):
        self.assertIsNone(q.HANDOFF_PROMPT_PATTERN.search("please do a session handoff"))
        self.assertIsNone(q.HANDOFF_PROMPT_PATTERN.search("hand off to another agent"))


class CodexHandoffPromptPatternTest(unittest.TestCase):
    def test_matches_session_handoff_anywhere(self):
        self.assertIsNotNone(c.HANDOFF_PROMPT_PATTERN.search("/session-handoff"))
        self.assertIsNotNone(c.HANDOFF_PROMPT_PATTERN.search("session-handoff"))
        self.assertIsNotNone(
            c.HANDOFF_PROMPT_PATTERN.search("wrap up:\nsession-handoff\nkeep it short")
        )

    def test_does_not_match_handoff_prose(self):
        self.assertIsNone(c.HANDOFF_PROMPT_PATTERN.search("please do a session handoff"))
        self.assertIsNone(c.HANDOFF_PROMPT_PATTERN.search("hand off to another agent"))


class InjectedPromptPatternTest(unittest.TestCase):
    def test_matches_task_notification(self):
        self.assertIsNotNone(
            q.INJECTED_PROMPT_PATTERN.search(
                "<task-notification>Agent foo completed</task-notification>"
            )
        )

    def test_matches_task_notification_with_attrs(self):
        self.assertIsNotNone(
            q.INJECTED_PROMPT_PATTERN.search('<task-notification id="123">done</task-notification>')
        )

    def test_no_match_ordinary_prompt(self):
        self.assertIsNone(q.INJECTED_PROMPT_PATTERN.search("please fix the bug in the parser"))


if __name__ == "__main__":
    unittest.main()
