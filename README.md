<div align="center">

![WeChat Chat Exporter](docs/banner.png)

# WeChat Chat Exporter 🗂️

**Decrypt · Export · Archive your WeChat PC chat history**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey?logo=windows)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

A Python tool that **decrypts WeChat PC (Windows) databases** and exports every conversation into a beautiful, self-contained HTML file — complete with images, voice messages, videos, file attachments, and animated custom stickers.

> **Platform:** Windows only (key extraction uses the Windows API)  
> **WeChat:** PC / Desktop version (not mobile)


---

## ✨ Features

| Feature | Details |
|---|---|
| 🔓 **Key extraction** | Reads WeChat's encryption key directly from process memory |
| 💬 **Full chat export** | Every conversation exported as a standalone HTML page |
| 🖼️ **Images** | Decrypts WeChat's `.dat` format (XOR / AES-ECB) and embeds images inline |
| 🎙️ **Voice messages** | Decodes SILK audio → WAV, embeds a playback widget + transcription |
| 📹 **Videos** | Embeds MP4 video messages with playback controls |
| 📎 **File attachments** | Download buttons for any sent/received documents |
| 🔗 **Link previews** | Renders shared article cards with title and URL |
| 🎭 **Custom stickers** | Downloads and renders animated GIF/WebP stickers from WeChat CDN |
| 🌐 **Dashboard** | A main `index.html` listing all conversations |
| 🔍 **Search** | Live in-page search that highlights matching messages |
| 📅 **Date dividers** | Messages grouped by date for easy reading |
| ⚡ **Filtering** | Export only certain contacts, or a specific date range |

---

## 📋 Requirements

- **Windows 10 / 11**
- **Python 3.9+** ([download](https://www.python.org/downloads/))
- **WeChat PC** installed, with at least one chat history on disk
- **Administrator rights** for the key extraction step only

---

## 🚀 Quick Start

### 1 — Clone or download the project

```
git clone https://github.com/KeepingJones/wechat-extract-ai.git
cd wechat-extract-ai
```

Or download and extract the ZIP from the GitHub page.

### 2 — Install Python dependencies

```
pip install -r requirements.txt
```

<details>
<summary>What gets installed?</summary>

| Package | Used for |
|---|---|
| `pycryptodome` | AES decryption for `.dat` image files |
| `jinja2` | HTML template rendering |
| `zstandard` | Decompressing zstd-compressed message content |
| `pilk` | SILK audio codec → WAV (voice messages) |
| `SpeechRecognition` | Voice transcription via Google Speech API |

</details>

### 3 — Run the setup wizard

```
python setup_config.py
```

This will:
- Auto-detect your WeChat data folder
- Ask a few simple questions
- Write `config.json` for you

### 4 — Extract the encryption key

**Open WeChat and log in first**, then run (as Administrator):

```
python key_finder.py
```

Right-click your terminal → *Run as administrator*, then run the command above.  
The key is saved automatically into `config.json`.

### 5 — Decrypt the databases

```
python decryptor.py
```

Decrypted `.db` files are written to the `decrypted/` folder (ignored by git).

### 6 — Export chats to HTML

```
python exporter.py
```

Then open `export/index.html` in any web browser. Done! 🎉

---

## 🗂️ Project Structure

```
wechat-exporter/
├── setup_config.py        ← START HERE — interactive config wizard
├── key_finder.py          ← Step 2 — extracts the database key from memory
├── decryptor.py           ← Step 3 — decrypts WeChat SQLCipher databases
├── exporter.py            ← Step 4 — parses messages and renders HTML
│
├── templates/
│   ├── dashboard.html     ← Jinja2 template for the contacts dashboard
│   └── chat.html          ← Jinja2 template for individual chat pages
│
├── config.json            ← Your config (auto-generated, NOT committed)
├── config.example.json    ← Template showing the config structure
├── requirements.txt       ← Python dependencies
│
└── export/                ← Output (gitignored)
    ├── index.html         ← Main dashboard — open this in your browser
    ├── html/              ← Individual chat HTML files
    ├── image/             ← Decrypted images
    ├── voice/             ← Decoded voice WAV files
    ├── video/             ← Video files
    ├── file/              ← Document attachments
    └── sticker/           ← Downloaded custom sticker images
```

---

## ⚙️ Configuration Reference (`config.json`)

The setup wizard creates this for you, but here are all the fields:

```json
{
  "wechat_db_dir": "C:/Users/YOU/OneDrive/Documents/xwechat_files/wxid_XXXX/db_storage",
  "output_dir":    "C:/path/to/wechat-exporter/export",
  "voice_language": "en-US",
  "key":            "automatically filled by key_finder.py",
  "candidate_keys": ["automatically filled by key_finder.py"],
  "image_aes_key":  "automatically filled by key_finder.py",
  "image_xor_key":  25
}
```

| Field | Description |
|---|---|
| `wechat_db_dir` | Path to WeChat's `db_storage` folder |
| `output_dir` | Where exported files are written (defaults to `./export`) |
| `voice_language` | BCP-47 speech language tag (see table below) |
| `key` | 64-char hex SQLCipher key — filled by `key_finder.py` |
| `candidate_keys` | All keys found by `key_finder.py` (usually just one) |
| `image_aes_key` | AES key for V2 `.dat` image decryption |
| `image_xor_key` | XOR byte for image decryption (usually `25` on PC) |

### Voice Language Options

| Tag | Language |
|---|---|
| `en-US` | English (United States) |
| `en-GB` | English (United Kingdom) |
| `zh-CN` | Mandarin Chinese (Simplified) |
| `zh-TW` | Mandarin Chinese (Traditional) |
| `ja-JP` | Japanese |
| `ko-KR` | Korean |
| `fr-FR` | French |
| `de-DE` | German |
| `es-ES` | Spanish |

---

## 🔧 Advanced Usage

### Export a single contact

```
python exporter.py --contact "Alice"
```

### Export messages in a date range

```
python exporter.py --since 2024-01-01 --until 2024-12-31
```

### Skip already-exported chats (incremental mode)

```
python exporter.py --incremental
```

### Combine filters

```
python exporter.py --contact "Work Group" --since 2025-01-01 --incremental
```

---

## 🔐 Privacy & Security

> ⚠️ Your exported chats contain private messages and personal media.

- `config.json` is in `.gitignore` — **never commit it** as it contains your encryption key
- `decrypted/` and `export/` are also gitignored — your messages stay local
- The encryption key extracted by `key_finder.py` is unique to your machine and WeChat install
- Transcription uses Google's free Speech Recognition API over the internet — if you prefer offline transcription, set `voice_language` to an empty string (`""`) to disable it

---

## 🛠️ How It Works

### Key Extraction (`key_finder.py`)
WeChat PC stores the SQLCipher key in process memory. This script uses the Windows API (`ReadProcessMemory`, `VirtualQueryEx`) to scan WeChat's address space for 32-byte hex patterns and verifies each candidate against an actual database page.

### Database Decryption (`decryptor.py`)
WeChat uses SQLCipher with AES-256-CBC encryption, one page at a time (4096 bytes). Each page has a 16-byte IV stored in the reserved space at the end. The decryptor reconstructs standard SQLite files.

### Message Parsing (`exporter.py`)
Messages live in `Msg_<MD5(username)>` tables across multiple `message_*.db` files. The exporter:
1. Loads contact names from `contact_contact.db`
2. Scans all `message_message_*.db` databases
3. Decodes each message based on its type number

### Message Type Reference

| Type | Content |
|---|---|
| `1` | Plain text |
| `3` | Image (`.dat` file, XOR or AES encrypted) |
| `34` | Voice (SILK encoded, decoded to WAV) |
| `43` | Video |
| `47` | Custom sticker (XML → CDN URL → downloaded GIF/PNG/WebP) |
| `48` | Location |
| `49` | App message: link card, file attachment, payment, quoted reply |
| `50` | Voice/video call |
| `10000` | System notification |

### Image Decryption
WeChat encodes images as `.dat` files in two formats:
- **V1**: Single XOR key (`cfcd208495d565ef`) applied to the entire file
- **V2**: AES-ECB encrypted header + XOR tail (key extracted alongside the DB key)

### Voice Messages
Voice is encoded in SILK V3 format. `pilk` decodes SILK → PCM, which is wrapped in a WAV container. Google Speech Recognition transcribes the content (responses cached in `transcription_cache.json`).

### Custom Stickers
Sticker messages contain zstd-compressed XML with an `<emoji>` element holding the CDN URL and MD5. The exporter fetches from WeChat's CDN, detects the format, and caches locally. Failed CDN downloads (expired URLs) are recorded in `failed_stickers.json` to skip them on future runs.

---

## ❓ Troubleshooting

### "Access Denied" when running key_finder.py
→ Run your terminal **as Administrator**: right-click Terminal or PowerShell → *Run as administrator*

### "WeChat/Weixin process not found"
→ Make sure WeChat is open **and you are logged in** before running `key_finder.py`

### "Decrypted contact database not found"
→ Run `python decryptor.py` before `exporter.py`

### Images show as broken / missing
→ The `image_aes_key` and `image_xor_key` in `config.json` may need to be updated. These vary by WeChat version. Try re-running `key_finder.py` if you recently updated WeChat.

### Voice messages have no transcription
→ The file is still decoded and playable — transcription requires an internet connection and uses Google's API, which may be rate-limited. Transcriptions are cached after the first successful run.

### Stickers don't appear
→ WeChat CDN links expire. If a sticker fails to download, it's recorded in `failed_stickers.json`. Delete this file to retry all failed stickers on next run.

---

## 🤝 Contributing

Pull requests welcome! Please:
- Keep sensitive data (keys, personal exports) out of any PRs
- Test changes against a real WeChat database if possible
- Follow the existing code style

---

## ⚠️ Disclaimer

This tool is for **personal use only** — to backup and read your own WeChat conversations. Do not use it to access other people's messages without their explicit consent. Use at your own risk and in accordance with WeChat's terms of service.
