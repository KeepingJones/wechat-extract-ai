#!/usr/bin/env python3
"""
setup_config.py — Interactive first-run setup wizard for wechat-exporter.

Run this script once before anything else:
    python setup_config.py

It will:
  1. Ask where your WeChat db_storage folder is
  2. Write a config.json ready for key_finder.py and exporter.py
"""

import os
import sys
import json
import glob


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def auto_find_wechat_dir():
    """Try to locate the WeChat db_storage folder automatically on Windows."""
    candidates = []

    # Common locations on Windows
    roots = [
        os.path.expandvars(r"%USERPROFILE%\OneDrive\Documents\xwechat_files"),
        os.path.expandvars(r"%USERPROFILE%\Documents\xwechat_files"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Roaming\Tencent\WeChat"),
        os.path.expandvars(r"%APPDATA%\Tencent\WeChat"),
    ]

    for root in roots:
        if os.path.isdir(root):
            # Look for wxid_*/db_storage pattern
            pattern = os.path.join(root, "wxid_*", "db_storage")
            found = glob.glob(pattern)
            candidates.extend(found)

            # Also try non-prefixed pattern (some installs)
            pattern2 = os.path.join(root, "*", "db_storage")
            for f in glob.glob(pattern2):
                if f not in candidates:
                    candidates.append(f)

    return candidates


def choose_from_list(items, label):
    """Let the user choose an item from a numbered list."""
    print(f"\n{label}")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item}")
    print(f"  {len(items)+1}. Enter path manually")

    while True:
        choice = input(f"\nEnter number [1-{len(items)+1}]: ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(items):
                return items[idx - 1]
            elif idx == len(items) + 1:
                return None
        except ValueError:
            pass
        print("  Invalid choice. Please try again.")


# ─────────────────────────────────────────────────────────────────────────────
# Main setup
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  WeChat Exporter — First-Run Setup Wizard")
    print("=" * 60)

    project_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(project_dir, "config.json")

    # Load existing config if present
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            print(f"\n[!] Found existing config.json — values shown in brackets are current.")
        except Exception:
            pass

    # ── Step 1: WeChat db_storage path ───────────────────────────────────────
    print("\n" + "─" * 60)
    print("STEP 1 — WeChat Database Folder")
    print("─" * 60)
    print("This is the 'db_storage' folder inside your WeChat data directory.")
    print("It usually looks like:")
    print("  C:\\Users\\YOU\\OneDrive\\Documents\\xwechat_files\\wxid_XXXX\\db_storage")

    existing = config.get("wechat_db_dir", "")
    if existing:
        print(f"\n  Current value: {existing}")

    candidates = auto_find_wechat_dir()

    wechat_db_dir = None
    if candidates:
        print(f"\n  Auto-detected {len(candidates)} candidate location(s):")
        chosen = choose_from_list(candidates, "Select your WeChat db_storage folder:")
        if chosen:
            wechat_db_dir = chosen

    if not wechat_db_dir:
        while True:
            val = input(
                f"\n  Enter full path to db_storage folder"
                + (f" [{existing}]" if existing else "")
                + ": "
            ).strip()
            if not val and existing:
                wechat_db_dir = existing
                break
            if val and os.path.isdir(val):
                wechat_db_dir = val
                break
            print("  [!] Directory not found. Please check the path and try again.")

    print(f"  ✓ WeChat DB dir: {wechat_db_dir}")

    # ── Step 2: Output directory ──────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("STEP 2 — Output Directory")
    print("─" * 60)
    default_output = os.path.join(project_dir, "export")
    existing_out = config.get("output_dir", default_output)
    print(f"  Where should exported HTML and media be saved?")
    val = input(f"  Output directory [{existing_out}]: ").strip()
    output_dir = val if val else existing_out
    print(f"  ✓ Output dir: {output_dir}")

    # ── Step 3: Voice language ────────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("STEP 3 — Voice Message Transcription Language")
    print("─" * 60)
    print("  Language used for speech recognition on voice messages.")
    print("  Examples: en-US, zh-CN, zh-TW, ja-JP, ko-KR, fr-FR, de-DE")
    existing_lang = config.get("voice_language", "en-US")
    val = input(f"  Language tag [{existing_lang}]: ").strip()
    voice_language = val if val else existing_lang
    print(f"  ✓ Voice language: {voice_language}")

    # ── Write config ──────────────────────────────────────────────────────────
    config["wechat_db_dir"] = wechat_db_dir
    config["output_dir"] = output_dir
    config["voice_language"] = voice_language

    # Preserve existing keys if already set
    if "key" not in config:
        config["key"] = ""
    if "candidate_keys" not in config:
        config["candidate_keys"] = []
    if "image_aes_key" not in config:
        config["image_aes_key"] = ""
    if "image_xor_key" not in config:
        config["image_xor_key"] = 25

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print("\n" + "=" * 60)
    print("  config.json written successfully!")
    print("=" * 60)
    print("""
NEXT STEPS:
  1. Make sure WeChat is open and you are logged in.

  2. Run the key finder (requires Administrator on Windows):
       python key_finder.py
     This scans WeChat's memory for the database encryption key.

  3. Decrypt the databases:
       python decryptor.py

  4. Export all chats to HTML:
       python exporter.py

  5. Open the dashboard:
       export/index.html   (in any web browser)

OPTIONAL FLAGS for exporter.py:
  --contact "Alice"        Only export chats matching "Alice"
  --since   2024-01-01     Only messages on/after this date
  --until   2024-12-31     Only messages on/before this date
  --incremental            Skip contacts already exported
""")


if __name__ == "__main__":
    main()
