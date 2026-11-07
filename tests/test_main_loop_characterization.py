# -*- coding: utf-8 -*-
"""
特性テスト: agent.main() の購読ループ

現行の振る舞い（接続先 URL・User-Agent・バックオフ・行処理・
エラー時の標準出力）を、urlopen / sleep / handle をモックして固定する。
実ネットワークには一切触れない。

対応候補: C-018 main の責務集中 / C-021 ベースURL直書き / C-022 時間系
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent  # noqa: E402


class StopLoop(Exception):
    """sleep モックからループを抜けるための番兵例外。"""


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)


CFG = {"topic": "kids-notify-test123", "voice": "Kyoko", "speak": True}


def run_main(urlopen_side_effect, sleep_side_effect=None, cfg=None, handle=None):
    """main() をモック下で実行。sleep が StopLoop を送出して終了する前提。"""
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if sleep_side_effect is not None:
            sleep_side_effect(len(sleeps))
        else:
            raise StopLoop()

    buf = io.StringIO()
    with mock.patch.object(agent, "load_config", return_value=CFG if cfg is None else cfg), \
         mock.patch.object(agent.urllib.request, "urlopen") as urlopen, \
         mock.patch.object(agent.time, "sleep", side_effect=fake_sleep), \
         mock.patch.object(agent, "handle", handle or mock.MagicMock()) as handle_mock, \
         redirect_stdout(buf):
        urlopen.side_effect = urlopen_side_effect
        try:
            agent.main()
        except StopLoop:
            pass
    return urlopen, handle_mock, sleeps, buf.getvalue()


class MainStartupTest(unittest.TestCase):
    def test_startup_log_and_url_and_user_agent(self):
        urlopen, _, _, out = run_main([OSError("down")])
        self.assertIn("Start listening: kids-notify-test123", out)
        req = urlopen.call_args.args[0]
        # C-021: 購読 URL は https://ntfy.sh/<topic>/json（現行の固定値）
        self.assertEqual(req.full_url, "https://ntfy.sh/kids-notify-test123/json")
        self.assertEqual(req.get_header("User-agent"), "kids-notify/1.0")

    def test_urlopen_called_with_timeout_none(self):
        urlopen, _, _, _ = run_main([OSError("down")])
        self.assertIsNone(urlopen.call_args.kwargs["timeout"])

    def test_missing_topic_key_raises_key_error_before_connecting(self):
        buf = io.StringIO()
        with mock.patch.object(agent, "load_config", return_value={}), \
             mock.patch.object(agent.urllib.request, "urlopen") as urlopen, \
             redirect_stdout(buf):
            with self.assertRaises(KeyError):
                agent.main()
        urlopen.assert_not_called()
        self.assertNotIn("Start listening", buf.getvalue())


class MainStreamProcessingTest(unittest.TestCase):
    def test_valid_json_lines_are_dispatched_to_handle(self):
        line1 = json.dumps({"event": "message", "message": "hi"}).encode()
        line2 = json.dumps({"event": "open"}).encode()
        handle = mock.MagicMock()
        run_main(
            [FakeResponse([line1 + b"\n", line2 + b"\n"]), OSError("down")],
            handle=handle,
        )
        self.assertEqual(handle.call_count, 2)
        self.assertEqual(handle.call_args_list[0].args[0], {"event": "message", "message": "hi"})
        self.assertEqual(handle.call_args_list[0].args[1], CFG)
        self.assertEqual(handle.call_args_list[1].args[0], {"event": "open"})

    def test_empty_and_blank_lines_are_skipped(self):
        handle = mock.MagicMock()
        run_main([FakeResponse([b"\n", b"   \n", b""]), OSError("down")], handle=handle)
        handle.assert_not_called()

    def test_invalid_json_line_logs_parse_error_and_continues(self):
        good = json.dumps({"event": "message", "message": "after"}).encode()
        handle = mock.MagicMock()
        _, _, _, out = run_main(
            [FakeResponse([b"this is not json\n", good + b"\n"]), OSError("down")],
            handle=handle,
        )
        self.assertIn("parse error:", out)
        handle.assert_called_once()
        self.assertEqual(handle.call_args.args[0]["message"], "after")

    def test_handle_exception_is_reported_as_parse_error_and_continues(self):
        line = json.dumps({"event": "message", "message": "x"}).encode()
        handle = mock.MagicMock(side_effect=[RuntimeError("handle boom"), None])
        _, _, _, out = run_main(
            [FakeResponse([line + b"\n", line + b"\n"]), OSError("down")],
            handle=handle,
        )
        self.assertIn("parse error: handle boom", out)
        self.assertEqual(handle.call_count, 2)

    def test_invalid_utf8_bytes_are_ignored_not_fatal(self):
        # decode("utf-8", "ignore") の現行仕様: 不正バイトは落ちて処理が続く
        good = json.dumps({"event": "message", "message": "ok"}).encode()
        handle = mock.MagicMock()
        run_main(
            [FakeResponse([b"\xff\xfe\n", good + b"\n"]), OSError("down")],
            handle=handle,
        )
        handle.assert_called_once()


class MainBackoffTest(unittest.TestCase):
    def test_first_failure_sleeps_3_and_logs(self):
        _, _, sleeps, out = run_main([OSError("refused")])
        self.assertEqual(sleeps, [3])
        self.assertIn("connection error: refused (retry in 3s)", out)

    def test_backoff_doubles_and_caps_at_60(self):
        # C-022: 3→6→12→24→48→60→60（上限 60）の現行系列を固定
        def stop_on_seventh(n):
            if n >= 7:
                raise StopLoop()

        _, _, sleeps, _ = run_main(
            [OSError("down")] * 7, sleep_side_effect=stop_on_seventh
        )
        self.assertEqual(sleeps, [3, 6, 12, 24, 48, 60, 60])

    def test_backoff_resets_to_3_after_successful_connection(self):
        def stop_on_second(n):
            if n >= 2:
                raise StopLoop()

        good = json.dumps({"event": "open"}).encode()
        _, _, sleeps, out = run_main(
            [OSError("first"), FakeResponse([good + b"\n"]), OSError("second")],
            sleep_side_effect=stop_on_second,
        )
        self.assertEqual(sleeps, [3, 3])
        self.assertIn("connection error: second (retry in 3s)", out)

    def test_connection_error_log_uses_current_backoff_value(self):
        def stop_on_third(n):
            if n >= 3:
                raise StopLoop()

        _, _, _, out = run_main(
            [OSError("e1"), OSError("e2"), OSError("e3")],
            sleep_side_effect=stop_on_third,
        )
        self.assertIn("connection error: e1 (retry in 3s)", out)
        self.assertIn("connection error: e2 (retry in 6s)", out)
        self.assertIn("connection error: e3 (retry in 12s)", out)


if __name__ == "__main__":
    unittest.main()
