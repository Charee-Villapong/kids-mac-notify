# -*- coding: utf-8 -*-
"""
特性テスト: 配布物（zip）と install.sh / uninstall.sh

スクリプトは launchctl / curl / 実 HOME を対象にするため VM では実行せず、
配布物の構成と、スクリプトが固定しているパス・文面・plist 内容を
「配布仕様」として固定する（実行系の確認は実働確認が必要な領域）。

対応候補: C-017 配布zip / C-020 install/uninstall / C-021 / C-023
"""
import os
import unittest
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_repo(name):
    with open(os.path.join(REPO, name), "r", encoding="utf-8") as f:
        return f.read()


class ZipContentsTest(unittest.TestCase):
    def setUp(self):
        self.zip_path = os.path.join(REPO, "kids-mac-notify.zip")
        with zipfile.ZipFile(self.zip_path) as zf:
            self.names = zf.namelist()
            self.payload = {n: zf.read(n) for n in self.names if not n.endswith("/")}

    def test_zip_contains_exactly_the_four_distribution_files(self):
        self.assertEqual(
            sorted(self.names),
            sorted(
                [
                    "kids-mac-notify/",
                    "kids-mac-notify/agent.py",
                    "kids-mac-notify/install.sh",
                    "kids-mac-notify/uninstall.sh",
                    "kids-mac-notify/README.md",
                ]
            ),
        )

    def test_zip_payloads_match_repo_files_byte_for_byte(self):
        # C-017: zip とリポジトリ実ファイルの乖離を検知する固定
        for member, blob in self.payload.items():
            repo_name = os.path.basename(member)
            with open(os.path.join(REPO, repo_name), "rb") as f:
                self.assertEqual(blob, f.read(), f"{repo_name} differs from zip")


class InstallScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = read_repo("install.sh")

    def test_shebang_set_e_and_cd_to_script_dir(self):
        self.assertTrue(self.script.startswith("#!/bin/bash"))
        self.assertIn("set -e", self.script)
        self.assertIn('cd "$(dirname "$0")"', self.script)

    def test_install_locations(self):
        self.assertIn(
            'APP_DIR="$HOME/Library/Application Support/KidsNotify"', self.script
        )
        self.assertIn(
            'PLIST="$HOME/Library/LaunchAgents/com.kidsnotify.plist"', self.script
        )
        self.assertIn('"$HOME/Library/Logs"', self.script)

    def test_existing_config_topic_is_reused(self):
        self.assertIn('if [ -f "$APP_DIR/config.json" ]', self.script)
        self.assertIn("['topic']", self.script)

    def test_new_topic_format_and_config_template(self):
        # トピック = kids-notify- + 英小文字数字 20 文字（現行仕様）
        self.assertIn("tr -dc 'a-z0-9'", self.script)
        self.assertIn("head -c 20", self.script)
        self.assertIn('TOPIC="kids-notify-$RAND"', self.script)
        # C-023: 初期 config の文面・デフォルト
        self.assertIn(
            '{"topic": "$TOPIC", "voice": "Kyoko", "speak": true}', self.script
        )

    def test_agent_py_is_copied_into_app_dir(self):
        self.assertIn('cp agent.py "$APP_DIR/agent.py"', self.script)

    def test_plist_contents(self):
        s = self.script
        self.assertIn("<key>Label</key><string>com.kidsnotify</string>", s)
        self.assertIn("<string>/usr/bin/python3</string>", s)
        self.assertIn("<string>$APP_DIR/agent.py</string>", s)
        self.assertIn("<key>RunAtLoad</key><true/>", s)
        self.assertIn("<key>KeepAlive</key><true/>", s)
        self.assertIn(
            "<string>$HOME/Library/Logs/kidsnotify.log</string>", s
        )

    def test_launchctl_unload_then_load(self):
        unload_at = self.script.index('launchctl unload "$PLIST"')
        load_at = self.script.index('launchctl load "$PLIST"')
        self.assertLess(unload_at, load_at)
        self.assertIn('launchctl unload "$PLIST" 2>/dev/null || true', self.script)

    def test_completion_output_and_test_sending(self):
        s = self.script
        self.assertIn("セットアップ完了！", s)
        self.assertIn("送信先トピック: $TOPIC", s)
        self.assertIn("https://ntfy.sh/$TOPIC", s)
        self.assertIn("-H 'Title: おうちから'", s)
        self.assertIn("セットアップできたよ！この通知が見えたら成功", s)


class UninstallScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = read_repo("uninstall.sh")

    def test_shebang_and_plist_path_matches_install(self):
        self.assertTrue(self.script.startswith("#!/bin/bash"))
        self.assertIn(
            'PLIST="$HOME/Library/LaunchAgents/com.kidsnotify.plist"', self.script
        )

    def test_unloads_then_removes_plist_and_app_dir(self):
        s = self.script
        self.assertIn('launchctl unload "$PLIST" 2>/dev/null || true', s)
        self.assertIn('rm -f "$PLIST"', s)
        self.assertIn(
            'rm -rf "$HOME/Library/Application Support/KidsNotify"', s
        )
        self.assertLess(s.index("launchctl unload"), s.index('rm -f "$PLIST"'))

    def test_completion_message(self):
        self.assertIn("削除しました。", self.script)

    def test_uninstall_does_not_remove_log_file(self):
        # 現行仕様: ログ (~/Library/Logs/kidsnotify.log) は削除対象外
        self.assertNotIn("kidsnotify.log", self.script)


class ScriptsExecutableTest(unittest.TestCase):
    def test_shell_scripts_and_agent_are_executable(self):
        for name in ("install.sh", "uninstall.sh", "agent.py"):
            with self.subTest(name=name):
                self.assertTrue(
                    os.access(os.path.join(REPO, name), os.X_OK), name
                )


class ReadmeSpecTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = read_repo("README.md")

    def test_notify_only_usage_is_documented(self):
        self.assertIn("NOTIFY:", self.readme)
        self.assertIn("通知だけ", self.readme)

    def test_topic_secrecy_warning_is_documented(self):
        self.assertIn("合言葉", self.readme)
        self.assertIn("載せないでください", self.readme)

    def test_uninstall_path_is_documented(self):
        self.assertIn("./uninstall.sh", self.readme)
        self.assertIn("./install.sh", self.readme)


if __name__ == "__main__":
    unittest.main()
