# -*- coding: utf-8 -*-
"""
特性テスト（現状固定テスト）: agent.py

実装の内部構造ではなく、README・運用仕様と現行の観測可能な振る舞い
（入出力／外部コマンドへの引数／標準出力）から固定する。
外部作用（osascript・say・ファイル）はすべてモック／一時ファイルで
切り分け、実ネットワーク・実 Mac には触れない。

対応する将来のリファクタリング候補:
  C-016 show_dialog/show_notification の重複
  C-019 handle の責務混在
  C-022 時間系マジックナンバー
  C-023 文面・デフォルト直書き
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent  # noqa: E402


def run_handle(data, cfg):
    """handle() を外部作用モック下で実行し、(manager, stdout) を返す。"""
    manager = mock.MagicMock()
    buf = io.StringIO()
    with mock.patch.object(agent, "show_notification", manager.show_notification), \
         mock.patch.object(agent, "show_dialog", manager.show_dialog), \
         mock.patch.object(agent, "speak", manager.speak), \
         redirect_stdout(buf):
        result = agent.handle(data, cfg)
    return manager, buf.getvalue(), result


class LoadConfigTest(unittest.TestCase):
    def _write_config(self, text):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.write(text)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return tmp.name

    def test_returns_parsed_dict_exactly(self):
        path = self._write_config(
            '{"topic": "kids-notify-abc123", "voice": "Kyoko", "speak": true}'
        )
        with mock.patch.object(agent, "CONFIG_PATH", path):
            cfg = agent.load_config()
        self.assertEqual(
            cfg,
            {"topic": "kids-notify-abc123", "voice": "Kyoko", "speak": True},
        )

    def test_preserves_types_and_extra_keys(self):
        path = self._write_config('{"topic": "t", "speak": false, "extra": 42}')
        with mock.patch.object(agent, "CONFIG_PATH", path):
            cfg = agent.load_config()
        self.assertIs(cfg["speak"], False)
        self.assertEqual(cfg["extra"], 42)

    def test_japanese_values_round_trip_utf8(self):
        path = self._write_config('{"topic": "t", "voice": "きょーこ"}')
        with mock.patch.object(agent, "CONFIG_PATH", path):
            self.assertEqual(agent.load_config()["voice"], "きょーこ")

    def test_empty_object_returns_empty_dict(self):
        path = self._write_config("{}")
        with mock.patch.object(agent, "CONFIG_PATH", path):
            self.assertEqual(agent.load_config(), {})

    def test_missing_file_raises_file_not_found(self):
        with mock.patch.object(agent, "CONFIG_PATH", "/nonexistent-dir-xyz/config.json"):
            with self.assertRaises(FileNotFoundError):
                agent.load_config()

    def test_malformed_json_raises_decode_error(self):
        path = self._write_config("{not json")
        with mock.patch.object(agent, "CONFIG_PATH", path):
            with self.assertRaises(json.JSONDecodeError):
                agent.load_config()

    def test_config_path_is_config_json_beside_agent(self):
        self.assertEqual(os.path.basename(agent.CONFIG_PATH), "config.json")
        self.assertEqual(
            os.path.dirname(agent.CONFIG_PATH),
            os.path.dirname(os.path.abspath(agent.__file__)),
        )


class ShowDialogTest(unittest.TestCase):
    def _call(self, title="タイトル", message="本文です"):
        buf = io.StringIO()
        with mock.patch.object(agent.subprocess, "run") as run, redirect_stdout(buf):
            agent.show_dialog(title, message)
        return run, buf.getvalue()

    def test_invokes_osascript_with_env_indirection(self):
        run, _ = self._call()
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "/usr/bin/osascript")
        self.assertEqual(args[0][1], "-e")
        script = args[0][2]
        # 文面はスクリプト文字列に直書きされず、環境変数経由で渡る（現行仕様）
        self.assertNotIn("タイトル", script)
        self.assertNotIn("本文です", script)
        self.assertIn('system attribute "KIDS_TITLE"', script)
        self.assertIn('system attribute "KIDS_MSG"', script)
        env = kwargs["env"]
        self.assertEqual(env["KIDS_TITLE"], "タイトル")
        self.assertEqual(env["KIDS_MSG"], "本文です")

    def test_env_inherits_process_environment(self):
        with mock.patch.dict(os.environ, {"MUSE_TEST_MARKER": "present"}):
            run, _ = self._call()
        self.assertEqual(run.call_args.kwargs["env"]["MUSE_TEST_MARKER"], "present")

    def test_script_is_caution_dialog_with_ok_button(self):
        run, _ = self._call()
        script = run.call_args.args[0][2]
        self.assertIn("display dialog m with title t", script)
        self.assertIn('buttons {"OK"}', script)
        self.assertIn('default button "OK"', script)
        self.assertIn("with icon caution", script)

    def test_giving_up_after_120_and_timeout_130(self):
        # C-022: 表示側 120 秒 / プロセス側タイムアウト 130 秒の現行値
        run, _ = self._call()
        script = run.call_args.args[0][2]
        self.assertIn("giving up after 120", script)
        self.assertEqual(run.call_args.kwargs["timeout"], 130)

    def test_subprocess_error_is_swallowed_and_logged(self):
        buf = io.StringIO()
        with mock.patch.object(
            agent.subprocess, "run", side_effect=RuntimeError("boom")
        ), redirect_stdout(buf):
            agent.show_dialog("t", "m")  # 例外が伝播しないこと
        self.assertIn("dialog error: boom", buf.getvalue())


class ShowNotificationTest(unittest.TestCase):
    def _call(self, title="タイトル", message="本文です"):
        buf = io.StringIO()
        with mock.patch.object(agent.subprocess, "run") as run, redirect_stdout(buf):
            agent.show_notification(title, message)
        return run, buf.getvalue()

    def test_invokes_osascript_with_env_indirection(self):
        run, _ = self._call()
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "/usr/bin/osascript")
        self.assertEqual(args[0][1], "-e")
        script = args[0][2]
        self.assertNotIn("本文です", script)
        self.assertIn('system attribute "KIDS_TITLE"', script)
        self.assertIn('system attribute "KIDS_MSG"', script)
        self.assertEqual(kwargs["env"]["KIDS_TITLE"], "タイトル")
        self.assertEqual(kwargs["env"]["KIDS_MSG"], "本文です")

    def test_script_is_notification_with_glass_sound(self):
        run, _ = self._call()
        script = run.call_args.args[0][2]
        self.assertIn("display notification m with title t", script)
        self.assertIn('sound name "Glass"', script)
        self.assertNotIn("display dialog", script)

    def test_timeout_is_10(self):
        run, _ = self._call()
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_subprocess_error_is_swallowed_and_logged(self):
        buf = io.StringIO()
        with mock.patch.object(
            agent.subprocess, "run", side_effect=RuntimeError("nope")
        ), redirect_stdout(buf):
            agent.show_notification("t", "m")
        self.assertIn("notification error: nope", buf.getvalue())


class DialogNotificationCommonTest(unittest.TestCase):
    """C-016: 2 関数の共通部分（osascript 経路・環境変数キー）の固定。"""

    def test_both_use_same_osascript_and_env_keys(self):
        with mock.patch.object(agent.subprocess, "run") as run:
            agent.show_dialog("T", "M")
            agent.show_notification("T", "M")
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][0], "/usr/bin/osascript")
            self.assertEqual(call.kwargs["env"]["KIDS_TITLE"], "T")
            self.assertEqual(call.kwargs["env"]["KIDS_MSG"], "M")


class SpeakTest(unittest.TestCase):
    def test_empty_voice_does_nothing(self):
        for voice in ("", None):
            with self.subTest(voice=voice):
                with mock.patch.object(agent.subprocess, "run") as run:
                    agent.speak("こんにちは", voice)
                run.assert_not_called()

    def test_success_single_call_with_voice_and_timeout_60(self):
        with mock.patch.object(agent.subprocess, "run") as run:
            run.return_value.returncode = 0
            agent.speak("静かにして", "Kyoko")
        run.assert_called_once_with(
            ["/usr/bin/say", "-v", "Kyoko", "静かにして"], timeout=60
        )

    def test_nonzero_returncode_falls_back_to_default_voice(self):
        with mock.patch.object(agent.subprocess, "run") as run:
            run.return_value.returncode = 1
            agent.speak("お風呂だよ", "Kyoko")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[1],
            mock.call(["/usr/bin/say", "お風呂だよ"], timeout=60),
        )

    def test_message_passed_verbatim(self):
        with mock.patch.object(agent.subprocess, "run") as run:
            run.return_value.returncode = 0
            agent.speak("  声 でかいよ〜  ", "Alex")
        self.assertEqual(run.call_args.args[0][3], "  声 でかいよ〜  ")

    def test_first_call_exception_is_swallowed_without_fallback(self):
        buf = io.StringIO()
        with mock.patch.object(
            agent.subprocess, "run", side_effect=RuntimeError("say boom")
        ) as run, redirect_stdout(buf):
            agent.speak("hi", "Kyoko")
        self.assertEqual(run.call_count, 1)
        self.assertIn("say error: say boom", buf.getvalue())

    def test_fallback_exception_is_swallowed_and_logged(self):
        def fake_run(argv, timeout=None):
            if "-v" in argv:
                return mock.Mock(returncode=1)
            raise RuntimeError("fallback boom")

        buf = io.StringIO()
        with mock.patch.object(
            agent.subprocess, "run", side_effect=fake_run
        ), redirect_stdout(buf):
            agent.speak("hi", "Kyoko")
        self.assertIn("say error: fallback boom", buf.getvalue())


class HandleEventGateTest(unittest.TestCase):
    def test_non_message_events_are_ignored(self):
        for data in (
            {"event": "open", "message": "hi"},
            {"event": "keepalive", "message": "hi"},
            {"event": "Message", "message": "hi"},  # 大文字小文字は区別される
            {"event": None, "message": "hi"},
            {"message": "hi"},  # event 欠落
            {},
        ):
            with self.subTest(data=data):
                manager, out, result = run_handle(data, {})
                manager.show_notification.assert_not_called()
                manager.show_dialog.assert_not_called()
                manager.speak.assert_not_called()
                self.assertEqual(out, "")
                self.assertIsNone(result)

    def test_empty_messages_are_ignored(self):
        for data in (
            {"event": "message"},
            {"event": "message", "message": None},
            {"event": "message", "message": ""},
            {"event": "message", "message": "   \n\t "},
        ):
            with self.subTest(data=data):
                manager, out, _ = run_handle(data, {})
                manager.show_notification.assert_not_called()
                manager.show_dialog.assert_not_called()
                manager.speak.assert_not_called()
                self.assertEqual(out, "")


class HandleNormalFlowTest(unittest.TestCase):
    def test_full_flow_order_notification_then_speak_then_dialog(self):
        manager, _, _ = run_handle(
            {"event": "message", "title": "おうちから", "message": "静かにして"},
            {"voice": "Kyoko", "speak": True},
        )
        self.assertEqual(
            [c[0] for c in manager.mock_calls],
            ["show_notification", "speak", "show_dialog"],
        )

    def test_arguments_passed_to_each_channel(self):
        manager, _, _ = run_handle(
            {"event": "message", "title": "パパ", "message": "お風呂だよ"},
            {"voice": "Alex", "speak": True},
        )
        manager.show_notification.assert_called_once_with("パパ", "お風呂だよ")
        manager.speak.assert_called_once_with("お風呂だよ", "Alex")
        manager.show_dialog.assert_called_once_with("パパ", "お風呂だよ")

    def test_message_is_stripped_before_display(self):
        manager, out, _ = run_handle(
            {"event": "message", "message": "  こんにちは \n"}, {}
        )
        manager.show_notification.assert_called_once_with("おうちから", "こんにちは")
        manager.show_dialog.assert_called_once_with("おうちから", "こんにちは")
        self.assertIn("こんにちは", out)
        self.assertNotIn("  こんにちは ", out)

    def test_default_title_when_missing_none_or_empty(self):
        for data in (
            {"event": "message", "message": "hi"},
            {"event": "message", "title": None, "message": "hi"},
            {"event": "message", "title": "", "message": "hi"},
        ):
            with self.subTest(data=data):
                manager, _, _ = run_handle(data, {})
                manager.show_notification.assert_called_once_with("おうちから", "hi")

    def test_explicit_title_is_preserved(self):
        manager, _, _ = run_handle(
            {"event": "message", "title": "ママから", "message": "hi"}, {}
        )
        manager.show_dialog.assert_called_once_with("ママから", "hi")

    def test_log_line_format(self):
        _, out, _ = run_handle(
            {"event": "message", "title": "おうちから", "message": "テスト"}, {}
        )
        self.assertRegex(out, r"^\[\d{2}:\d{2}:\d{2}\] おうちから: テスト\n$")

    def test_speak_defaults_on_and_voice_kyoko_when_cfg_empty(self):
        manager, _, _ = run_handle({"event": "message", "message": "hi"}, {})
        manager.speak.assert_called_once_with("hi", "Kyoko")

    def test_speak_disabled_by_config(self):
        manager, _, _ = run_handle(
            {"event": "message", "message": "hi"}, {"speak": False}
        )
        manager.speak.assert_not_called()
        manager.show_notification.assert_called_once()
        manager.show_dialog.assert_called_once()

    def test_speak_falsy_zero_also_disables(self):
        manager, _, _ = run_handle({"event": "message", "message": "hi"}, {"speak": 0})
        manager.speak.assert_not_called()

    def test_voice_none_is_passed_through_to_speak(self):
        manager, _, _ = run_handle(
            {"event": "message", "message": "hi"}, {"voice": None}
        )
        manager.speak.assert_called_once_with("hi", None)


class HandleNotifyOnlyTest(unittest.TestCase):
    def test_notify_prefix_variants(self):
        for raw in ("NOTIFY:静かに", "notify:静かに", "Notify: 静かに", "nOtIfY:静かに"):
            with self.subTest(raw=raw):
                manager, _, _ = run_handle({"event": "message", "message": raw}, {})
                manager.show_notification.assert_called_once_with(
                    "おうちから", "静かに"
                )
                manager.speak.assert_not_called()
                manager.show_dialog.assert_not_called()

    def test_notify_prefix_strips_following_spaces(self):
        manager, _, _ = run_handle(
            {"event": "message", "message": "NOTIFY:   お風呂だよ  "}, {}
        )
        manager.show_notification.assert_called_once_with("おうちから", "お風呂だよ")

    def test_leading_spaces_before_notify_still_notify_only(self):
        # handle 先頭で strip されるため、前置空白があっても接頭辞扱いになる
        manager, _, _ = run_handle(
            {"event": "message", "message": "  NOTIFY: hi"}, {}
        )
        manager.show_notification.assert_called_once_with("おうちから", "hi")
        manager.show_dialog.assert_not_called()

    def test_notify_bare_prefix_sends_empty_notification(self):
        # 接頭辞除去後に空になっても通知は送られる（現行の振る舞いを固定）
        manager, out, _ = run_handle({"event": "message", "message": "NOTIFY:"}, {})
        manager.show_notification.assert_called_once_with("おうちから", "")
        manager.speak.assert_not_called()
        manager.show_dialog.assert_not_called()
        self.assertRegex(out, r"^\[\d{2}:\d{2}:\d{2}\] おうちから: \n$")

    def test_notify_without_colon_is_normal_message(self):
        manager, _, _ = run_handle({"event": "message", "message": "NOTIFY hi"}, {})
        manager.show_dialog.assert_called_once_with("おうちから", "NOTIFY hi")
        manager.speak.assert_called_once()

    def test_notifyx_is_normal_message(self):
        manager, _, _ = run_handle({"event": "message", "message": "NOTIFYX: hi"}, {})
        manager.show_dialog.assert_called_once_with("おうちから", "NOTIFYX: hi")

    def test_prefix_not_at_start_is_normal_message(self):
        manager, _, _ = run_handle(
            {"event": "message", "message": "xNOTIFY: hi"}, {}
        )
        manager.show_dialog.assert_called_once_with("おうちから", "xNOTIFY: hi")
        manager.speak.assert_called_once()

    def test_double_notify_prefix_removes_only_first(self):
        manager, _, _ = run_handle(
            {"event": "message", "message": "NOTIFY:NOTIFY: hi"}, {}
        )
        manager.show_notification.assert_called_once_with(
            "おうちから", "NOTIFY: hi"
        )
        manager.show_dialog.assert_not_called()

    def test_notify_only_keeps_explicit_title(self):
        manager, _, _ = run_handle(
            {"event": "message", "title": "パパ", "message": "NOTIFY: hi"}, {}
        )
        manager.show_notification.assert_called_once_with("パパ", "hi")


if __name__ == "__main__":
    unittest.main()
