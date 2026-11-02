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


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def show_dialog(title, message):
    env = dict(os.environ, KIDS_TITLE=title, KIDS_MSG=message)
    script = (
        'set t to system attribute "KIDS_TITLE"\n'
        'set m to system attribute "KIDS_MSG"\n'
        'display dialog m with title t buttons {"OK"} default button "OK" '
        'with icon caution giving up after 120'
    )
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], env=env, timeout=130)
    except Exception as e:
        print(f"dialog error: {e}", flush=True)


def show_notification(title, message):
    env = dict(os.environ, KIDS_TITLE=title, KIDS_MSG=message)
    script = (
        'set t to system attribute "KIDS_TITLE"\n'
        'set m to system attribute "KIDS_MSG"\n'
        'display notification m with title t sound name "Glass"'
    )
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], env=env, timeout=10)
    except Exception as e:
        print(f"notification error: {e}", flush=True)


def speak(message, voice):
    if not voice:
        return
    try:
        r = subprocess.run(["/usr/bin/say", "-v", voice, message], timeout=60)
        if r.returncode != 0:
            subprocess.run(["/usr/bin/say", message], timeout=60)
    except Exception as e:
        print(f"say error: {e}", flush=True)


def handle(data, cfg):
    if data.get("event") != "message":
        return
    title = data.get("title") or "おうちから"
    message = (data.get("message") or "").strip()
    if not message:
        return
    # 先頭のモード指定: NOTIFY: = 通知のみ / それ以外 = ダイアログ+通知+読み上げ
    notify_only = False
    if message.upper().startswith("NOTIFY:"):
        notify_only = True
        message = message[7:].strip()
    print(f"[{time.strftime('%H:%M:%S')}] {title}: {message}", flush=True)
    show_notification(title, message)
    if cfg.get("speak", True) and not notify_only:
        speak(message, cfg.get("voice", "Kyoko"))
    if not notify_only:
        show_dialog(title, message)


def main():
    cfg = load_config()
    topic = cfg["topic"]
    url = f"https://ntfy.sh/{topic}/json"
    print(f"Start listening: {topic}", flush=True)
    backoff = 3
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kids-notify/1.0"})
            with urllib.request.urlopen(req, timeout=None) as resp:
                backoff = 3
                for raw in resp:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line:
                        continue
                    try:
                        handle(json.loads(line), cfg)
                    except Exception as e:
                        print(f"parse error: {e}", flush=True)
        except Exception as e:
            print(f"connection error: {e} (retry in {backoff}s)", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    main()
