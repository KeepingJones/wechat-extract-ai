<div align="center">

![WeChat Chat Exporter](docs/banner.png)

# WeChat Chat Exporter

**Decrypt · Export · Archive your WeChat PC chat history**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey?logo=windows)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

A Python tool that **decrypts WeChat PC (Windows) databases** and exports every conversation into a beautiful, self-contained HTML file — complete with images, voice messages, videos, file attachments, and animated custom stickers.

> **Platform:** Windows 10 / 11 only — the key extraction step uses the Windows memory API  
> **WeChat:** PC / Desktop version only (not the mobile app)

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔓 **Key extraction** | Reads WeChat's encryption key directly from process memory |
| 💬 **Full chat export** | Every conversation exported as a standalone HTML page |
| 🖼️ **Images** | Decrypts WeChat's `.dat` image format (XOR / AES-ECB) and embeds inline |
| 🎙️ **Voice messages** | Decodes SILK audio → WAV, embeds a playback widget + optional transcription |
| 📹 **Videos** | Embeds MP4 video messages with native playback controls |
| 📎 **File attachments** | Download buttons for any sent/received documents |
| 🔗 **Link previews** | Renders shared article cards with title and URL |
| 🎭 **Custom stickers** | Downloads and renders animated GIF/WebP stickers from WeChat CDN |
| 🌐 **Dashboard** | A main `index.html` listing all conversations with message counts |
| 🔍 **Live search** | In-page search that highlights matching messages in real time |
| 📅 **Date dividers** | Messages grouped by date for easy reading |
| ⚡ **CLI filters** | Export a specific contact, date range, or use incremental mode |

---

## 📋 Requirements

- **Windows 10 or 11**
- **Python 3.9+** — [download here](https://www.python.org/downloads/)
- **WeChat PC** — installed and with chat history stored on disk
- **Administrator rights** — only needed for the key extraction step

---

## 🚀 Quick Start

### Step 1 — Get the project

```bash
git clone https://github.com/KeepingJones/wechat-extract-ai.git
cd wechat-extract-ai
```

Or click **Code → Download ZIP** on the GitHub page and extract it.

### Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

<details>
<summary>📦 What gets installed?</summary>

| Package | Purpose |
|---|---|
| `pycryptodome` | AES decryption of `.dat` image files |
| `jinja2` | HTML template rendering |
| `zstandard` | Decompresses zstd-compressed message payloads |
| `pilk` | Decodes SILK V3 audio (voice messages) → WAV |
| `SpeechRecognition` | Voice message transcription via Google Speech API |

</details>

### Step 3 — Run the setup wizard

```bash
python setup_config.py
```

This interactively:
- Auto-detects your WeChat data folder
- Asks for output location and language preference
- Writes `config.json` ready for the next steps

### Step 4 — Extract the encryption key

Make sure **WeChat is open and you are logged in**, then run this **as Administrator**:

```bash
python key_finder.py
```

> **How to run as Administrator:** Right-click Command Prompt or PowerShell → *Run as administrator*, then run the command.

The encryption key is found automatically and saved to `config.json`.

### Step 5 — Decrypt the databases

```bash
python decryptor.py
```

Decrypted SQLite files are written to the `decrypted/` folder.

### Step 6 — Export chats to HTML

```bash
python exporter.py
```

Open `export/index.html` in any web browser. Done! 🎉

---

## 🗂️ Project Structure

```
wechat-extract-ai/
│
├── setup_config.py        ← START HERE — interactive config wizard
├── key_finder.py          ← Step 2 — extracts the database encryption key
├── decryptor.py           ← Step 3 — decrypts SQLCipher databases
├── exporter.py            ← Step 4 — parses messages and renders HTML
│
├── templates/
│   ├── dashboard.html     ← Jinja2 template for the contacts dashboard
│   └── chat.html          ← Jinja2 template for individual chat pages
│
├── docs/
│   └── banner.png         ← README header image
│
├── tools/                 ← Developer inspection scripts (not needed for normal use)
│   └── README.md          ← Describes each tool
│
├── config.json            ← Your local config — auto-generated, NOT committed to git
├── config.example.json    ← Safe template showing the config structure
├── requirements.txt       ← Python dependencies
├── LICENSE
└── README.md
```

Generated output (gitignored, stays on your machine):

```
export/
├── index.html         ← Main dashboard — open this in your browser
├── html/              ← One HTML file per conversation
├── image/             ← Decrypted images
├── voice/             ← Decoded voice WAV files
├── video/             ← Video files
├── file/              ← Document attachments
└── sticker/           ← Downloaded custom sticker images
```

---

## ⚙️ Configuration Reference

`config.json` is created by `setup_config.py`. You can also edit it manually:

```json
{
  "wechat_db_dir":  "C:/Users/YOU/OneDrive/Documents/xwechat_files/wxid_XXXX/db_storage",
  "output_dir":     "C:/Users/YOU/wechat-extract-ai/export",
  "voice_language": "en-US",
  "key":            "← filled automatically by key_finder.py",
  "candidate_keys": ["← filled automatically by key_finder.py"],
  "image_aes_key":  "← filled automatically by key_finder.py",
  "image_xor_key":  25
}
```

| Field | Required | Description |
|---|---|---|
| `wechat_db_dir` | ✅ | Full path to WeChat's `db_storage` folder |
| `output_dir` | ✅ | Where exported HTML and media are written |
| `voice_language` | ✅ | BCP-47 language code for speech recognition (see below) |
| `key` | Auto | 64-char hex SQLCipher key — set by `key_finder.py` |
| `candidate_keys` | Auto | All keys found by `key_finder.py` (usually just one) |
| `image_aes_key` | Auto | AES key for V2 `.dat` image decryption |
| `image_xor_key` | Auto | XOR byte for image decryption (typically `25` on WeChat PC) |

### Voice Language Codes

| Code | Language |
|---|---|
| `en-US` | English (United States) |
| `en-GB` | English (United Kingdom) |
| `zh-CN` | Mandarin Chinese — Simplified |
| `zh-TW` | Mandarin Chinese — Traditional |
| `ja-JP` | Japanese |
| `ko-KR` | Korean |
| `fr-FR` | French |
| `de-DE` | German |
| `es-ES` | Spanish (Spain) |

Set `voice_language` to `""` to skip transcription entirely.

---

## 🔧 Advanced Usage

### Export a single contact

```bash
python exporter.py --contact "Alice"
```

Matches any contact whose name or WeChat ID contains "Alice" (case-insensitive).

### Export a date range

```bash
python exporter.py --since 2024-01-01 --until 2024-12-31
```

### Incremental mode — skip already-exported chats

```bash
python exporter.py --incremental
```

### Combine options

```bash
python exporter.py --contact "Work Group" --since 2025-01-01 --incremental
```

---

## 🔐 Privacy & Security

> ⚠️ **Exported chat histories contain private messages and personal media. Keep them local.**

- `config.json` is listed in `.gitignore` — **never commit it**, as it contains your encryption key
- `decrypted/` and `export/` are also gitignored — your data stays on your machine only
- The key extracted by `key_finder.py` is unique to your WeChat install and machine
- Voice transcription uses Google's free Speech Recognition API (internet required). Results are cached locally in `transcription_cache.json` after the first run. Set `voice_language: ""` to disable

---

## 🛠️ How It Works

### 1. Key Extraction (`key_finder.py`)

WeChat PC stores the 32-byte SQLCipher key as a hex string in heap memory. The script uses Windows APIs (`ReadProcessMemory`, `VirtualQueryEx`) to scan WeChat's address space for 64-character hex patterns and verifies each candidate by attempting to AES-decrypt the first 4096-byte page of a real database.

### 2. Database Decryption (`decryptor.py`)

WeChat uses **SQLCipher** with AES-256-CBC encryption applied one page at a time (4096 bytes per page). Each page stores a 16-byte IV in a reserved region at its end. Page 1 also has a 16-byte random salt prefix. The script tries both SQLCipher 3 (48-byte reserve) and SQLCipher 4 (80-byte reserve) automatically, then writes standard unencrypted SQLite files.

### 3. Message Parsing (`exporter.py`)

Messages are stored in `Msg_<MD5(username)>` tables spread across multiple `message_message_*.db` files. The exporter:

1. Loads contact display names from `contact_contact.db`
2. Discovers all `Msg_*` tables across all message databases
3. Decodes every message according to its type number

### Message Type Reference

| Type | Content | How it's handled |
|---|---|---|
| `1` | Plain text | Rendered as-is |
| `3` | Image | `.dat` file decrypted (XOR or AES-ECB), displayed inline |
| `34` | Voice message | SILK V3 decoded → WAV, embedded player + Google transcription |
| `43` | Video | MP4 embedded with native `<video>` player |
| `47` | Custom sticker | XML parsed → CDN URL fetched → GIF/PNG/WebP cached locally |
| `48` | Location share | Label and coordinates displayed |
| `49` | App message | Link cards, file downloads, quoted replies, WeChat Pay receipts |
| `50` | Voice / video call | Call type and duration displayed |
| `10000` | System notification | Shown as a system event row |

### Image Decryption (`.dat` files)

WeChat stores images as `.dat` files in one of two formats:

- **V1** — XOR with the fixed key `cfcd208495d565ef` byte-by-byte
- **V2** — AES-ECB encrypted header + XOR tail (keys extracted from memory by `key_finder.py`)

### Voice Messages

Audio is stored in **SILK V3** format. `pilk` decodes SILK → raw PCM, which is wrapped into a standard WAV container. Google Speech Recognition is then used to transcribe the content. All successful transcriptions are saved to `transcription_cache.json` so they are not re-fetched on subsequent runs.

### Custom Stickers

Sticker message content is zstd-compressed XML containing an `<emoji>` element with the sticker's CDN URL and MD5 hash. The exporter downloads the image, detects its format (GIF / PNG / WebP / JPG), saves it to `export/sticker/<md5>.<ext>`, and references it in the HTML. CDN links for older stickers may return 400 errors — these failures are cached in `failed_stickers.json` to prevent retrying them on future runs.

---

## ❓ Troubleshooting

### "Access Denied" when running `key_finder.py`
Right-click your terminal → **Run as administrator**, then try again.

### "WeChat/Weixin process not found"
WeChat must be **open and logged in** when you run `key_finder.py`. Start WeChat, log in, then run the script.

### "Decrypted contact database not found"
Run `python decryptor.py` before `python exporter.py`.

### Images are broken or missing
The `image_aes_key` / `image_xor_key` in `config.json` may be stale after a WeChat update. Re-run `python key_finder.py` to refresh them, then re-run `python decryptor.py` and `python exporter.py`.

### Voice messages have no transcription
The WAV file is still playable — transcription requires an active internet connection and uses Google's Speech API, which can occasionally be rate-limited. Delete `transcription_cache.json` and re-run to retry failed entries.

### Stickers are missing
WeChat CDN links expire. Failed downloads are cached in `failed_stickers.json`. To retry them all, delete that file and re-run `python exporter.py`.

### `pilk` not found / SILK decode fails
Make sure you installed dependencies with `pip install -r requirements.txt`. On some systems you may also need the Visual C++ build tools: [download here](https://visualstudio.microsoft.com/visual-cpp-build-tools/).

---

## 🤝 Contributing

Pull requests are welcome. Please:
- Keep sensitive data (encryption keys, personal exports) out of any PRs
- Test changes against a real WeChat database where possible
- Follow the existing code style (PEP 8, descriptive function names)

---

## ⚠️ Disclaimer

This tool is intended for **personal use only** — to backup and read your own WeChat conversations. Do not use it to access another person's messages without their explicit consent. Use responsibly and at your own risk, in accordance with WeChat's terms of service.
