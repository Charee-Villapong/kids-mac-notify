#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kids Notify Agent for macOS
- ntfy.sh の自分専用トピックを常時購読し、届いたメッセージを
  画面中央のダイアログ + 通知 + 音声読み上げで表示する
- 依存ライブラリなし（標準ライブラリのみ）
設定: 同じフォルダの config.json  {"topic": "...", "voice": "Kyoko", "speak": true}
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")

# 接続先（ntfy.sh）のベースURL。購読URLはここから組み立てる
NTFY_BASE_URL = "https://ntfy.sh"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# AppleScript 冒頭部: 文面はスクリプトに直書きせず環境変数経由で受け取る
_ENV_PREAMBLE = (
    'set t to system attribute "KIDS_TITLE"\n'
    'set m to system attribute "KIDS_MSG"\n'
)


def _run_osascript(title, message, script, timeout, error_label):
    """osascript 実行の共通処理（環境変数の受け渡し＋例外時ログ）。"""
    env = dict(os.environ, KIDS_TITLE=title, KIDS_MSG=message)
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], env=env, timeout=timeout)
    except Exception as e:
        print(f"{error_label} error: {e}", flush=True)


def show_dialog(title, message):
    script = _ENV_PREAMBLE + (
        'display dialog m with title t buttons {"OK"} default button "OK" '
        'with icon caution giving up after 120'
    )
    _run_osascript(title, message, script, timeout=130, error_label="dialog")


def show_notification(title, message):
    script = _ENV_PREAMBLE + (
        'display notification m with title t sound name "Glass"'
    )
    _run_osascript(title, message, script, timeout=10, error_label="notification")


def speak(message, voice):
    if not voice:
        return
    try:
        r = subprocess.run(["/usr/bin/say", "-v", voice, message], timeout=60)
        if r.returncode != 0:
            subprocess.run(["/usr/bin/say", message], timeout=60)
    except Exception as e:
        print(f"say error: {e}", flush=True)


def _split_notify_only(message):
    """先頭のモード指定を取り除く。

    NOTIFY: = 通知のみ / それ以外 = ダイアログ+通知+読み上げ。
    (通知のみかどうか, 接頭辞を取り除いた本文) を返す。
    """
    if message.upper().startswith("NOTIFY:"):
        return True, message[7:].strip()
    return False, message


def _dispatch(title, message, notify_only, cfg):
    """ログを出して、通知→読み上げ→ダイアログの順に振り分ける。"""
    print(f"[{time.strftime('%H:%M:%S')}] {title}: {message}", flush=True)
    show_notification(title, message)
    if cfg.get("speak", True) and not notify_only:
        speak(message, cfg.get("voice", "Kyoko"))
    if not notify_only:
        show_dialog(title, message)


def handle(data, cfg):
    if data.get("event") != "message":
        return
    title = data.get("title") or "おうちから"
    message = (data.get("message") or "").strip()
    if not message:
        return
    notify_only, message = _split_notify_only(message)
    _dispatch(title, message, notify_only, cfg)


def _process_stream(resp, cfg):
    """購読ストリームの各行を JSON として解釈し handle() へ渡す。"""
    for raw in resp:
        line = raw.decode("utf-8", "ignore").strip()
        if not line:
            continue
        try:
            handle(json.loads(line), cfg)
        except Exception as e:
            print(f"parse error: {e}", flush=True)


def main():
    cfg = load_config()
    topic = cfg["topic"]
    url = f"{NTFY_BASE_URL}/{topic}/json"
    print(f"Start listening: {topic}", flush=True)
    backoff = 3
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kids-notify/1.0"})
            with urllib.request.urlopen(req, timeout=None) as resp:
                backoff = 3
                _process_stream(resp, cfg)
        except Exception as e:
            print(f"connection error: {e} (retry in {backoff}s)", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    main()
