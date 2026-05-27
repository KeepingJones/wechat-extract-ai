"""
exporter.py — WeChat Chat Exporter
===================================
Parses decrypted WeChat PC SQLite databases and renders every conversation
as a self-contained HTML file (plus plain-text mirrors).

Usage:
    python exporter.py                          # Export all chats
    python exporter.py --contact "Alice"        # One contact (substring match)
    python exporter.py --since 2024-01-01       # Messages on/after date
    python exporter.py --until 2024-12-31       # Messages on/before date
    python exporter.py --incremental            # Skip already-exported chats

Prerequisites:
    1. Run key_finder.py  (extracts encryption key from WeChat process memory)
    2. Run decryptor.py   (decrypts SQLCipher databases to ./decrypted/)
    3. Run this script    (renders HTML to the output_dir in config.json)

Supported message types:
    1     Plain text
    3     Image (.dat files, XOR / AES-ECB decryption)
    34    Voice message (SILK → WAV, Google Speech transcription)
    43    Video
    47    Custom sticker (CDN download, GIF / PNG / WebP)
    48    Location
    49    App messages: link cards, file attachments, quoted replies, payments
    50    Voice / video call
    10000 System notifications
"""
import os
import html
import re
import sys
import json
import sqlite3
import hashlib
import datetime
import struct
import argparse
import glob
import urllib.request
import xml.etree.ElementTree as ET
import zstandard as zstd
from jinja2 import Environment, FileSystemLoader
import tempfile
import shutil
import pilk

try:
    from Crypto.Cipher import AES
    from Crypto.Util import Padding
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

FAILED_STICKERS = set()


def safe_copy(src, dst):
    try:
        shutil.copy2(src, dst)
    except Exception:
        try:
            shutil.copy(src, dst)
        except Exception:
            try:
                shutil.copyfile(src, dst)
            except Exception as e:
                print(f"Error safe_copying from {src} to {dst}: {e}")
                return False
    return True


def get_avatar_color(username):
    colors = [
        "#3b82f6",
        "#10b981",
        "#f59e0b",
        "#ef4444",
        "#8b5cf6",
        "#ec4899",
        "#06b6d4",
        "#f43f5e",
    ]
    h = int(hashlib.md5(username.encode('utf-8')).hexdigest(), 16)
    return colors[h % len(colors)]


def get_initials(name):
    if not name:
        return "?"
    return name[0].upper()


def decompress_content(content):
    """Decompress zstd-compressed content and decode to str."""
    if isinstance(content, bytes) and content.startswith(b'\x28\xb5\x2f\xfd'):
        try:
            dctx = zstd.ZstdDecompressor()
            content = dctx.decompress(content)
        except Exception:
            pass
    if isinstance(content, bytes):
        return content.decode('utf-8', errors='ignore').strip()
    return str(content).strip()


def build_dir_index(directory):
    """Return {filename: full_path} for every file under directory (first occurrence wins)."""
    index = {}
    if not os.path.isdir(directory):
        return index
    for root, _dirs, files in os.walk(directory):
        for fname in files:
            if fname not in index:
                index[fname] = os.path.join(root, fname)
    return index


def extract_voice_trans(packed_data):
    if not packed_data:
        return None
    try:
        idx = packed_data.find(b'\x08\x02\x12')
        if idx != -1:
            pos = idx + 3
            if pos < len(packed_data):
                length = 0
                shift = 0
                while pos < len(packed_data):
                    b = packed_data[pos]
                    length |= (b & 0x7F) << shift
                    pos += 1
                    if not (b & 0x80):
                        break
                    shift += 7
                if pos + length <= len(packed_data):
                    text = packed_data[pos: pos + length].decode('utf-8', errors='ignore').strip()
                    if len(text) > 1 and text.endswith("X") and not text[-2].isalnum():
                        text = text[:-1].strip()
                    return text
    except Exception:
        pass
    return None


def extract_hex32_from_blob(blob):
    if not blob or not isinstance(blob, bytes):
        return None
    try:
        matches = re.findall(b'[a-fA-F0-9]{32}', blob)
        if matches:
            return matches[0].decode('ascii').lower()
    except Exception:
        pass
    return None


def extract_media_md5(packed_data):
    return extract_hex32_from_blob(packed_data)


def extract_md5_from_packed_info(blob):
    return extract_hex32_from_blob(blob)


V2_MAGIC_FULL = b'\x07\x08V2\x08\x07'
V1_MAGIC_FULL = b'\x07\x08V1\x08\x07'


def aligned_aes_block_size(aes_size):
    if aes_size % 16:
        return aes_size + (16 - aes_size % 16)
    return aes_size + 16


def detect_image_format(header_bytes):
    if header_bytes[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return 'jpg'
    if header_bytes[:4] == bytes([0x89, 0x50, 0x4E, 0x47]):
        return 'png'
    if header_bytes[:3] == b'GIF':
        return 'gif'
    if header_bytes[:2] == b'BM':
        return 'bmp'
    if header_bytes[:4] == b'RIFF' and len(header_bytes) >= 12 and header_bytes[8:12] == b'WEBP':
        return 'webp'
    if header_bytes[:4] == bytes([0x49, 0x49, 0x2A, 0x00]):
        return 'tif'
    return 'bin'


def decrypt_v2_image(dat_path, out_path_base, aes_key, xor_key=0x88):
    if not aes_key or not HAS_CRYPTO:
        return None, None
    if isinstance(aes_key, str):
        aes_key = aes_key.encode('ascii')[:16]
    if len(aes_key) < 16:
        return None, None
    if isinstance(xor_key, str):
        xor_key = int(xor_key, 0)

    try:
        with open(dat_path, 'rb') as f:
            data = f.read()
        if len(data) < 15:
            return None, None
        sig = data[:6]
        if sig not in (V2_MAGIC_FULL, V1_MAGIC_FULL):
            return None, None

        aes_size, xor_size = struct.unpack_from('<LL', data, 6)
        if sig == V1_MAGIC_FULL:
            aes_key = b'cfcd208495d565ef'

        aligned_aes_size = aligned_aes_block_size(aes_size)
        offset = 15
        if offset + aligned_aes_size > len(data):
            return None, None

        aes_data = data[offset:offset + aligned_aes_size]
        cipher = AES.new(aes_key[:16], AES.MODE_ECB)
        dec_aes = Padding.unpad(cipher.decrypt(aes_data), AES.block_size)
        offset += aligned_aes_size

        raw_end = len(data) - xor_size
        raw_data = data[offset:raw_end] if offset < raw_end else b''
        offset = raw_end

        xor_data = data[offset:]
        dec_xor = bytes(b ^ xor_key for b in xor_data)

        decrypted = dec_aes + raw_data + dec_xor
        fmt = detect_image_format(decrypted[:16])
        if decrypted[:4] == b'wxgf':
            fmt = 'hevc'
        elif fmt == 'bin':
            return None, None

        out_path = f"{out_path_base}.{fmt}"
        with open(out_path, 'wb') as f:
            f.write(decrypted)
        return out_path, fmt
    except Exception as e:
        print(f"Error decrypting V2 image {dat_path}: {e}")
        return None, None


def detect_xor_key(dat_path):
    IMAGE_MAGIC = {
        'png': [0x89, 0x50, 0x4E, 0x47],
        'gif': [0x47, 0x49, 0x46, 0x38],
        'tif': [0x49, 0x49, 0x2A, 0x00],
        'webp': [0x52, 0x49, 0x46, 0x46],
        'jpg': [0xFF, 0xD8, 0xFF],
    }
    try:
        with open(dat_path, 'rb') as f:
            header = f.read(16)
        if len(header) < 4:
            return None
        if header[:4] == b'\x07\x08\x56\x32':
            return None

        for fmt, magic in IMAGE_MAGIC.items():
            key = header[0] ^ magic[0]
            match = True
            for i in range(1, len(magic)):
                if i >= len(header):
                    break
                if (header[i] ^ key) != magic[i]:
                    match = False
                    break
            if match:
                return key
    except Exception:
        pass
    return None


def decrypt_xor_image(dat_path, out_path_base, xor_key=None):
    if xor_key is None:
        xor_key = detect_xor_key(dat_path)
    if xor_key is None:
        return None, None
    try:
        with open(dat_path, 'rb') as f:
            data = f.read()
        decrypted = bytes(b ^ xor_key for b in data)
        fmt = detect_image_format(decrypted[:16])
        out_path = f"{out_path_base}.{fmt}"
        with open(out_path, 'wb') as f:
            f.write(decrypted)
        return out_path, fmt
    except Exception as e:
        print(f"Error decrypting XOR image {dat_path}: {e}")
        return None, None


def decrypt_any_image(dat_path, out_path_base, aes_key, xor_key):
    try:
        with open(dat_path, 'rb') as f:
            head = f.read(6)
        if head == V2_MAGIC_FULL:
            return decrypt_v2_image(dat_path, out_path_base, aes_key, xor_key)
        if head == V1_MAGIC_FULL:
            return decrypt_v2_image(dat_path, out_path_base, b'cfcd208495d565ef', xor_key)
        return decrypt_xor_image(dat_path, out_path_base)
    except Exception:
        return None, None


def extract_voice_to_wav(voice_data, output_wav_path):
    if not voice_data:
        return False
    if voice_data[0:1] == b'\x02':
        silk_data = voice_data[1:]
    else:
        silk_data = voice_data

    if not silk_data.startswith(b'#!SILK_V3'):
        return False

    if not silk_data.endswith(b'\xff\xff'):
        silk_data += b'\xff\xff'

    silk_file = tempfile.mktemp(suffix=".silk")
    pcm_file = tempfile.mktemp(suffix=".pcm")
    try:
        with open(silk_file, "wb") as f:
            f.write(silk_data)

        pilk.decode(silk_file, pcm_file)

        if not os.path.exists(pcm_file):
            return False

        with open(pcm_file, "rb") as f_pcm:
            pcm_bytes = f_pcm.read()

        pcm_len = len(pcm_bytes)
        sample_rate = 24000
        channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8

        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',
            pcm_len + 36,
            b'WAVE',
            b'fmt ',
            16,
            1,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b'data',
            pcm_len
        )

        os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)
        with open(output_wav_path, "wb") as f_wav:
            f_wav.write(header)
            f_wav.write(pcm_bytes)

        return True
    except Exception as e:
        print(f"Error converting silk to wav: {e}")
        return False
    finally:
        if os.path.exists(silk_file):
            os.remove(silk_file)
        if os.path.exists(pcm_file):
            os.remove(pcm_file)


def find_file_in_dir(search_dir, target_filename):
    for root, dirs, files in os.walk(search_dir):
        if target_filename in files:
            return os.path.join(root, target_filename)
    return None


def format_file_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def parse_appmsg(content_str):
    title_text = ""
    app_type = 0
    url_text = ""

    try:
        if content_str.startswith("<msg>"):
            root = ET.fromstring(content_str)
        else:
            root = ET.fromstring(f"<msg>{content_str}</msg>")
        appmsg = root.find("appmsg")
        if appmsg is not None:
            title = appmsg.find("title")
            title_text = title.text if title is not None else ""
            type_node = appmsg.find("type")
            app_type = int(type_node.text) if type_node is not None else 0
            url = appmsg.find("url")
            url_text = url.text if url is not None else ""
            return title_text, app_type, url_text
    except Exception:
        pass

    # Regex fallback for malformed XML (unescaped ampersands, truncated content)
    try:
        title_match = re.search(r"<title>([\s\S]*?)</title>", content_str)
        title_text = html.unescape(title_match.group(1)) if title_match else ""

        type_match = re.search(r"<type>(\d+)</type>", content_str)
        app_type = int(type_match.group(1)) if type_match else 0

        url_match = re.search(r"<url>([\s\S]*?)</url>", content_str)
        url_text = html.unescape(url_match.group(1)) if url_match else ""
    except Exception:
        pass

    return title_text, app_type, url_text


def _parse_quoted_reply(content_str):
    """Extract (quoted_sender, quoted_text, reply_text) from a type-49/app_type-57 message."""
    quoted_name = ""
    quoted_text = ""
    reply_text = ""
    try:
        root_xml = ET.fromstring(content_str if content_str.startswith('<msg>') else f'<msg>{content_str}</msg>')
        appmsg = root_xml.find('appmsg')
        if appmsg is not None:
            title_node = appmsg.find('title')
            reply_text = title_node.text if title_node is not None else ""
            refermsg = appmsg.find('refermsg')
            if refermsg is not None:
                ref_content = refermsg.find('content')
                ref_displayname = refermsg.find('displayname')
                quoted_text = ref_content.text if ref_content is not None else ""
                quoted_name = ref_displayname.text if ref_displayname is not None else ""
                if quoted_text and len(quoted_text) > 100:
                    quoted_text = quoted_text[:100] + "…"
    except Exception:
        pass
    return quoted_name, quoted_text, reply_text


def format_message_content(
    msg_type, content, packed_info=None, talker_user=None, msg_local_id=None,
    create_time=None, wechat_db_dir=None, output_dir=None, aes_key=None,
    xor_key=0x88, decrypted_dir=None, trans_cache=None, voice_language="en-US",
    media_conn=None, video_index=None, file_index=None,
):
    if not content:
        return ""

    content_str = decompress_content(content)
    msg_type_clean = msg_type & 0xffffffff if msg_type is not None else 0

    # ── Plain text ────────────────────────────────────────────────────────────
    if msg_type_clean == 1:
        return html.escape(content_str)

    # ── Image ─────────────────────────────────────────────────────────────────
    elif msg_type_clean == 3:
        img_md5 = None
        if packed_info:
            img_md5 = extract_md5_from_packed_info(packed_info)

        if not img_md5:
            try:
                if content_str.startswith("<msg>"):
                    root = ET.fromstring(content_str)
                    img_node = root.find("img")
                    if img_node is not None:
                        img_md5 = img_node.attrib.get("md5")
            except Exception:
                pass

        if img_md5:
            chat_hash = hashlib.md5(talker_user.encode('utf-8')).hexdigest().lower()
            wechat_root = os.path.dirname(wechat_db_dir)
            attach_dir = os.path.join(wechat_root, "msg", "attach", chat_hash)

            dat_pattern = os.path.join(attach_dir, "*", "Img", f"{img_md5}*.dat")
            dat_files = glob.glob(dat_pattern)

            if dat_files:
                selected_dat = dat_files[0]
                for f in dat_files:
                    if not os.path.basename(f).startswith(img_md5 + "_t"):
                        selected_dat = f
                        break

                os.makedirs(os.path.join(output_dir, "image"), exist_ok=True)
                out_path_base = os.path.join(output_dir, "image", img_md5)

                ext_found = None
                for ext in ["jpg", "png", "gif", "webp", "bmp", "hevc"]:
                    if os.path.exists(f"{out_path_base}.{ext}"):
                        ext_found = ext
                        break

                if not ext_found:
                    dec_path, ext_found = decrypt_any_image(selected_dat, out_path_base, aes_key, xor_key)

                if ext_found:
                    return f'<div class="media-container img-container"><img src="../image/{img_md5}.{ext_found}" class="chat-image" onclick="openLightbox(this.src)" alt="Image" loading="lazy" /></div>'

        return f'<div class="media-placeholder">[Image (Missing MD5={html.escape(img_md5 or "unknown")})]</div>'

    # ── Voice message ─────────────────────────────────────────────────────────
    elif msg_type_clean == 34:
        duration = 0.0
        try:
            if content_str.startswith("<msg>"):
                root = ET.fromstring(content_str)
                voicemsg = root.find("voicemsg")
                if voicemsg is not None:
                    voicelength = voicemsg.attrib.get("voicelength", "0")
                    duration = float(voicelength) / 1000.0
        except Exception:
            pass

        trans_text = extract_voice_trans(packed_info)

        voice_wav_filename = f"{talker_user}_{msg_local_id}.wav"
        voice_wav_path = os.path.join(output_dir, "voice", voice_wav_filename)

        wav_exists = os.path.exists(voice_wav_path)
        if not wav_exists and media_conn:
            # Reuse pre-opened connection instead of opening per-message
            try:
                cursor_media = media_conn.cursor()
                cursor_media.execute("SELECT rowid FROM Name2Id WHERE user_name = ?", (talker_user,))
                chat_row = cursor_media.fetchone()
                if chat_row:
                    chat_name_id = chat_row[0]
                    cursor_media.execute(
                        "SELECT voice_data FROM VoiceInfo WHERE chat_name_id = ? AND local_id = ?",
                        (chat_name_id, msg_local_id)
                    )
                    voice_row = cursor_media.fetchone()
                    if voice_row and voice_row[0]:
                        wav_exists = extract_voice_to_wav(voice_row[0], voice_wav_path)
            except Exception as e:
                print(f"Error querying voice data: {e}")
        elif not wav_exists and decrypted_dir:
            # Fallback: open connection if media_conn not provided
            media_db_path = os.path.join(decrypted_dir, "message_media_0.db")
            if os.path.exists(media_db_path):
                try:
                    conn_media = sqlite3.connect(media_db_path)
                    cursor_media = conn_media.cursor()
                    cursor_media.execute("SELECT rowid FROM Name2Id WHERE user_name = ?", (talker_user,))
                    chat_row = cursor_media.fetchone()
                    if chat_row:
                        chat_name_id = chat_row[0]
                        cursor_media.execute(
                            "SELECT voice_data FROM VoiceInfo WHERE chat_name_id = ? AND local_id = ?",
                            (chat_name_id, msg_local_id)
                        )
                        voice_row = cursor_media.fetchone()
                        if voice_row and voice_row[0]:
                            wav_exists = extract_voice_to_wav(voice_row[0], voice_wav_path)
                    conn_media.close()
                except Exception as e:
                    print(f"Error querying voice data: {e}")

        if not trans_text:
            if trans_cache is not None and voice_wav_filename in trans_cache:
                trans_text = trans_cache[voice_wav_filename]
            elif wav_exists:
                try:
                    import speech_recognition as sr
                    r = sr.Recognizer()
                    with sr.AudioFile(voice_wav_path) as source:
                        audio = r.record(source)
                    trans_text = r.recognize_google(audio, language=voice_language).strip()
                    if trans_cache is not None:
                        trans_cache[voice_wav_filename] = trans_text
                    print(f"    [+] Transcribed voice note {voice_wav_filename}: \"{trans_text[:40]}...\"")
                except Exception:
                    if trans_cache is not None:
                        trans_cache[voice_wav_filename] = ""

        audio_html = ""
        if wav_exists:
            audio_html = f'<div class="voice-player"><audio src="../voice/{voice_wav_filename}" controls></audio></div>'

        trans_html = ""
        if trans_text:
            trans_html = f'<div class="voice-trans">" {html.escape(trans_text)} "</div>'

        return f'<div class="voice-msg-container">{audio_html}{trans_html}<div class="voice-meta">[Voice Message ({duration:.2f}s)]</div></div>'

    # ── Video ─────────────────────────────────────────────────────────────────
    elif msg_type_clean == 43:
        video_md5 = None
        if packed_info:
            video_md5 = extract_media_md5(packed_info)

        if video_md5:
            video_filename = f"{video_md5}.mp4"

            # Use pre-built index when available, fall back to os.walk
            if video_index is not None:
                local_video_path = video_index.get(video_filename)
            else:
                wechat_root = os.path.dirname(wechat_db_dir)
                video_dir = os.path.join(wechat_root, "msg", "video")
                local_video_path = find_file_in_dir(video_dir, video_filename)

            if local_video_path:
                os.makedirs(os.path.join(output_dir, "video"), exist_ok=True)
                dest_video_path = os.path.join(output_dir, "video", video_filename)

                if not os.path.exists(dest_video_path):
                    safe_copy(local_video_path, dest_video_path)

                thumb_filename = f"{video_md5}_thumb.jpg"
                if video_index is not None:
                    local_thumb_path = video_index.get(thumb_filename)
                else:
                    local_thumb_path = find_file_in_dir(os.path.dirname(local_video_path), thumb_filename)

                dest_thumb_path = os.path.join(output_dir, "video", thumb_filename)
                if local_thumb_path and not os.path.exists(dest_thumb_path):
                    safe_copy(local_thumb_path, dest_thumb_path)

                thumb_url = f"../video/{thumb_filename}" if os.path.exists(dest_thumb_path) else ""
                poster_attr = f'poster="{thumb_url}"' if thumb_url else ""
                return f'<div class="media-container video-container"><video src="../video/{video_filename}" controls {poster_attr} preload="metadata" class="chat-video"></video></div>'

        return f'<div class="media-placeholder">[Video (Missing MD5={html.escape(video_md5 or "unknown")})]</div>'

    # ── Sticker / emoji ───────────────────────────────────────────────────────
    elif msg_type_clean == 47:
        emoji_md5 = None
        cdnurl = None
        width = None
        height = None

        try:
            if content_str.startswith("<msg>"):
                root = ET.fromstring(content_str)
            else:
                root = ET.fromstring(f"<msg>{content_str}</msg>")
            emoji = root.find("emoji")
            if emoji is not None:
                emoji_md5 = emoji.attrib.get("md5")
                cdnurl = emoji.attrib.get("cdnurl")
                width = emoji.attrib.get("width")
                height = emoji.attrib.get("height")
        except Exception:
            pass

        if not emoji_md5:
            try:
                md5_match = re.search(r'md5="([a-fA-F0-9]{32})"', content_str)
                if md5_match:
                    emoji_md5 = md5_match.group(1)
                cdn_match = re.search(r'cdnurl="([^"]+)"', content_str)
                if cdn_match:
                    cdnurl = cdn_match.group(1)
                width_match = re.search(r'width="(\d+)"', content_str)
                if width_match:
                    width = width_match.group(1)
                height_match = re.search(r'height="(\d+)"', content_str)
                if height_match:
                    height = height_match.group(1)
            except Exception:
                pass

        if emoji_md5:
            sticker_dir = os.path.join(output_dir, "sticker")
            os.makedirs(sticker_dir, exist_ok=True)

            ext = None
            out_path_base = os.path.join(sticker_dir, emoji_md5)
            for possible_ext in ["gif", "png", "jpg", "webp"]:
                if os.path.exists(f"{out_path_base}.{possible_ext}"):
                    ext = possible_ext
                    break

            if not ext and cdnurl and emoji_md5 not in FAILED_STICKERS:
                cdnurl_clean = html.unescape(cdnurl)
                try:
                    req = urllib.request.Request(
                        cdnurl_clean,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                    )
                    with urllib.request.urlopen(req, timeout=3) as response:
                        sticker_data = response.read()

                    ext = detect_image_format(sticker_data[:16])
                    if ext == "bin" or not ext:
                        ext = "gif"

                    with open(f"{out_path_base}.{ext}", "wb") as f_out:
                        f_out.write(sticker_data)
                    print(f"    [+] Downloaded sticker {emoji_md5}.{ext}")
                except Exception as e:
                    FAILED_STICKERS.add(emoji_md5)
                    print(f"    [-] Failed to download sticker {emoji_md5}: {e}")

            if not ext:
                wechat_root = os.path.dirname(wechat_db_dir)
                local_emoji_path = os.path.join(
                    wechat_root, "business", "emoticon", "Persist",
                    emoji_md5[:2], emoji_md5
                )
                if os.path.exists(local_emoji_path):
                    try:
                        with open(local_emoji_path, "rb") as f_in:
                            sticker_data = f_in.read()
                        ext = detect_image_format(sticker_data[:16])
                        if ext != "bin":
                            with open(f"{out_path_base}.{ext}", "wb") as f_out:
                                f_out.write(sticker_data)
                            print(f"    [+] Copied local sticker {emoji_md5}.{ext}")
                        else:
                            ext = None
                    except Exception:
                        pass

            if ext:
                width_attr = f' width="{width}"' if width else ""
                height_attr = f' height="{height}"' if height else ""
                return f'<div class="media-container sticker-container"><img src="../sticker/{emoji_md5}.{ext}" class="chat-sticker" onclick="openLightbox(this.src)" alt="Sticker" loading="lazy"{width_attr}{height_attr} /></div>'

        return '<div class="media-placeholder">[Sticker (Missing or Offline)]</div>'

    # ── Location ──────────────────────────────────────────────────────────────
    elif msg_type_clean == 48:
        try:
            root = ET.fromstring(content_str if content_str.startswith('<msg>') else f'<msg>{content_str}</msg>')
            loc = root.find('location')
            if loc is not None:
                label = loc.attrib.get('label', '')
                poiname = loc.attrib.get('poiname', '') or loc.attrib.get('name', '')
                x = loc.attrib.get('x', '')
                y = loc.attrib.get('y', '')
                display = html.escape(poiname or label or 'Location')
                if x and y:
                    maps_url = html.escape(f'https://maps.google.com/?q={x},{y}')
                    return (
                        f'<div class="location-card">'
                        f'<a href="{maps_url}" target="_blank" rel="noopener">'
                        f'<span class="location-pin">&#128205;</span>'
                        f'<span class="location-name">{display}</span>'
                        f'<span class="location-coords">{html.escape(x)}, {html.escape(y)}</span>'
                        f'</a></div>'
                    )
                return (
                    f'<div class="location-card">'
                    f'<span class="location-pin">&#128205;</span>'
                    f'<span class="location-name">{display}</span>'
                    f'</div>'
                )
        except Exception:
            pass
        return '<div class="media-placeholder">[Location]</div>'

    # ── App messages (links, files, quoted replies, payments, …) ─────────────
    elif msg_type_clean == 49:
        title_text, app_type, url_text = parse_appmsg(content_str)

        if app_type == 5:
            # Shared link
            return (
                f'<div class="link-attachment">'
                f'<a href="{html.escape(url_text)}" target="_blank" rel="noopener" class="link-card">'
                f'<div class="link-title">{html.escape(title_text)}</div>'
                f'<div class="link-url">{html.escape(url_text)}</div>'
                f'</a></div>'
            )

        elif app_type == 6:
            # File attachment
            if file_index is not None:
                local_file_path = file_index.get(title_text)
            else:
                wechat_root = os.path.dirname(wechat_db_dir)
                file_dir = os.path.join(wechat_root, "msg", "file")
                local_file_path = find_file_in_dir(file_dir, title_text)

            file_ext = title_text.split(".")[-1].lower() if "." in title_text else "file"

            os.makedirs(os.path.join(output_dir, "file"), exist_ok=True)
            dest_file_path = os.path.join(output_dir, "file", title_text)

            file_copied = os.path.exists(dest_file_path)
            if not file_copied and local_file_path:
                file_copied = safe_copy(local_file_path, dest_file_path)

            if file_copied:
                file_size_str = format_file_size(os.path.getsize(dest_file_path))
                return (
                    f'<div class="file-attachment"><div class="file-card">'
                    f'<div class="file-icon {html.escape(file_ext)}">{html.escape(file_ext).upper()}</div>'
                    f'<div class="file-details">'
                    f'<div class="file-name" title="{html.escape(title_text)}">{html.escape(title_text)}</div>'
                    f'<div class="file-size">{file_size_str}</div>'
                    f'</div>'
                    f'<a href="../file/{html.escape(title_text)}" download class="file-download-btn">'
                    f'<svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" stroke-width="2" fill="none">'
                    f'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>'
                    f'</svg></a></div></div>'
                )
            else:
                return (
                    f'<div class="file-attachment missing"><div class="file-card">'
                    f'<div class="file-icon {html.escape(file_ext)}">{html.escape(file_ext).upper()}</div>'
                    f'<div class="file-details">'
                    f'<div class="file-name">{html.escape(title_text)}</div>'
                    f'<div class="file-size">Offline / Missing</div>'
                    f'</div></div></div>'
                )

        elif app_type == 57:
            # Quoted reply
            quoted_name, quoted_text, reply_text = _parse_quoted_reply(content_str)
            reply_text = reply_text or title_text
            quoted_html = ""
            if quoted_text or quoted_name:
                quoted_html = (
                    f'<div class="quoted-msg">'
                    f'<span class="quoted-sender">{html.escape(quoted_name)}</span>'
                    f'<span class="quoted-text">{html.escape(quoted_text)}</span>'
                    f'</div>'
                )
            return (
                f'<div class="reply-msg">'
                f'{quoted_html}'
                f'<div class="reply-content">{html.escape(reply_text)}</div>'
                f'</div>'
            )

        elif app_type == 2000:
            # WeChat Pay transfer
            return f'<div class="media-placeholder">[WeChat Pay: {html.escape(title_text or "Transfer")}]</div>'

        fallback_desc = title_text or content_str[:50]
        return f'<div class="media-placeholder">[Link/Attachment: {html.escape(fallback_desc)}...]</div>'

    # ── Voice / video call ────────────────────────────────────────────────────
    elif msg_type_clean == 50:
        try:
            root = ET.fromstring(content_str if content_str.startswith('<msg>') else f'<msg>{content_str}</msg>')
            voipbubble = root.find('voipbubble')
            if voipbubble is not None:
                invite_type = voipbubble.attrib.get('invitetype', '')
                duration = voipbubble.attrib.get('duration', '')
                call_label = 'Video Call' if invite_type == '2' else 'Voice Call'
                dur_str = f' · {duration}s' if duration else ''
                return f'<div class="media-placeholder">[{call_label}{dur_str}]</div>'
        except Exception:
            pass
        return '<div class="media-placeholder">[Call]</div>'

    # ── System message ────────────────────────────────────────────────────────
    elif msg_type_clean == 10000:
        return html.escape(content_str)

    else:
        return html.escape(content_str) if len(content_str) < 100 else f"[Media Type {msg_type_clean}]"


def get_message_preview(msg_type, content, packed_info=None, talker_user=None, msg_local_id=None, trans_cache=None):
    if not content:
        return ""

    content_str = decompress_content(content)
    msg_type_clean = msg_type & 0xffffffff if msg_type is not None else 0

    preview_text = ""
    if msg_type_clean == 1:
        preview_text = content_str
    elif msg_type_clean == 3:
        preview_text = "[Image]"
    elif msg_type_clean == 34:
        trans_text = extract_voice_trans(packed_info)
        if not trans_text and trans_cache:
            voice_wav_filename = f"{talker_user}_{msg_local_id}.wav"
            if voice_wav_filename in trans_cache:
                trans_text = trans_cache[voice_wav_filename]
        preview_text = f"[Voice: {trans_text}]" if trans_text else "[Voice Message]"
    elif msg_type_clean == 43:
        preview_text = "[Video]"
    elif msg_type_clean == 47:
        preview_text = "[Sticker]"
    elif msg_type_clean == 48:
        try:
            root = ET.fromstring(content_str if content_str.startswith('<msg>') else f'<msg>{content_str}</msg>')
            loc = root.find('location')
            if loc is not None:
                name = loc.attrib.get('poiname', '') or loc.attrib.get('label', '') or 'Location'
                preview_text = f"[Location: {name}]"
        except Exception:
            pass
        if not preview_text:
            preview_text = "[Location]"
    elif msg_type_clean == 49:
        try:
            if content_str.startswith("<msg>"):
                root = ET.fromstring(content_str)
                appmsg = root.find("appmsg")
                if appmsg is not None:
                    title = appmsg.find("title")
                    title_text = title.text if title is not None else ""
                    type_node = appmsg.find("type")
                    app_type = int(type_node.text) if type_node is not None else 0
                    if app_type == 5:
                        preview_text = f"[Link] {title_text}"
                    elif app_type == 6:
                        preview_text = f"[File] {title_text}"
                    elif app_type == 57:
                        preview_text = f"[Reply] {title_text}"
                    elif app_type == 2000:
                        preview_text = f"[WeChat Pay] {title_text}"
        except Exception:
            pass
        if not preview_text:
            preview_text = "[Link/Attachment]"
    elif msg_type_clean == 50:
        preview_text = "[Call]"
    elif msg_type_clean == 10000:
        preview_text = content_str
    else:
        preview_text = content_str if len(content_str) < 50 else f"[Media Type {msg_type_clean}]"

    cleaned = re.sub(r'<[^>]+>', '', preview_text)
    cleaned = html.unescape(cleaned)
    return cleaned.strip()


def get_columns_map(conn, table_name):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = [col[1].lower() for col in cursor.fetchall()]

    col_map = {}
    for col in columns:
        if col in ["local_id", "localid", "msgid"]:
            col_map["id"] = col
        elif col in ["create_time", "createtime", "timestamp"]:
            col_map["time"] = col
        elif col in ["message_content", "content", "strcontent", "body"]:
            col_map["content"] = col
        elif col in ["local_type", "type", "msgtype"]:
            col_map["type"] = col
        elif col in ["real_sender_id", "real_sender"]:
            col_map["real_sender_id"] = col
        elif col in ["issend", "issender", "is_sender"]:
            col_map["is_sender"] = col
        elif col in ["packed_info_data", "packed_info"]:
            col_map["packed_info"] = col
        elif col in ["talker", "strtalker", "sender"]:
            col_map["talker"] = col

    return col_map


def main():
    parser = argparse.ArgumentParser(description='Export WeChat chats to HTML/TXT')
    parser.add_argument('--contact', help='Only export chats matching this name or wxid (case-insensitive substring)')
    parser.add_argument('--since', metavar='YYYY-MM-DD', help='Only include messages on or after this date')
    parser.add_argument('--until', metavar='YYYY-MM-DD', help='Only include messages on or before this date')
    parser.add_argument('--incremental', action='store_true', help='Skip chats where the HTML file already exists')
    args = parser.parse_args()

    since_ts = None
    until_ts = None
    if args.since:
        try:
            since_ts = datetime.datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        except ValueError:
            print(f"[-] Invalid --since date: {args.since}. Use YYYY-MM-DD.")
            sys.exit(1)
    if args.until:
        try:
            # Include the full until day
            until_ts = (datetime.datetime.strptime(args.until, "%Y-%m-%d") + datetime.timedelta(days=1)).timestamp()
        except ValueError:
            print(f"[-] Invalid --until date: {args.until}. Use YYYY-MM-DD.")
            sys.exit(1)

    # Setup paths
    project_dir = os.path.dirname(__file__)
    config_path = os.path.join(project_dir, "config.json")
    decrypted_dir = os.path.join(project_dir, "decrypted")

    if not os.path.exists(config_path):
        print("[-] config.json not found!")
        sys.exit(1)

    with open(config_path, "r") as f:
        config = json.load(f)

    wechat_db_dir = config.get("wechat_db_dir", "")
    voice_language = config.get("voice_language", "en-US")

    # Load transcription cache
    trans_cache_path = os.path.join(project_dir, "transcription_cache.json")
    trans_cache = {}
    if os.path.exists(trans_cache_path):
        try:
            with open(trans_cache_path, "r", encoding="utf-8") as f:
                trans_cache = json.load(f)
            print(f"[+] Loaded {len(trans_cache)} cached transcriptions.")
        except Exception as e:
            print(f"[-] Error loading transcription cache: {e}")

    # Load failed stickers cache
    failed_stickers_path = os.path.join(project_dir, "failed_stickers.json")
    global FAILED_STICKERS
    if os.path.exists(failed_stickers_path):
        try:
            with open(failed_stickers_path, "r", encoding="utf-8") as f:
                failed_list = json.load(f)
                FAILED_STICKERS.update(failed_list)
            print(f"[+] Loaded {len(FAILED_STICKERS)} failed sticker cache entries.")
        except Exception as e:
            print(f"[-] Error loading failed stickers cache: {e}")

    output_dir = config.get("output_dir", os.path.join(project_dir, "export"))
    html_out_dir = os.path.join(output_dir, "html")
    txt_out_dir = os.path.join(output_dir, "txt")

    image_aes_key = config.get("image_aes_key", "")
    image_xor_key = config.get("image_xor_key", 0x88)

    os.makedirs(html_out_dir, exist_ok=True)
    os.makedirs(txt_out_dir, exist_ok=True)

    # Detect current user wxid from db path
    current_user_wxid = "Me"
    wxid_match = re.search(r'(wxid_[a-zA-Z0-9]+)', wechat_db_dir)
    if wxid_match:
        current_user_wxid = wxid_match.group(1)
        print(f"[+] Detected current user: {current_user_wxid}")

    # 1. Parse Contact Database
    contacts = {}
    contact_db_path = os.path.join(decrypted_dir, "contact_contact.db")
    if not os.path.exists(contact_db_path):
        print(f"[-] Decrypted contact database not found at {contact_db_path}")
        print("    Please run decryptor.py first.")
        sys.exit(1)

    print("[+] Loading contacts from contact.db...")
    try:
        conn = sqlite3.connect(contact_db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(Contact);")
        columns = [col[1].lower() for col in cursor.fetchall()]

        col_user = "username" if "username" in columns else columns[0]
        col_nick = "nick_name" if "nick_name" in columns else ("nickname" if "nickname" in columns else "")
        col_remark = "remark" if "remark" in columns else ""
        col_alias = "alias" if "alias" in columns else ""

        query_cols = [col_user]
        if col_nick:
            query_cols.append(col_nick)
        if col_remark:
            query_cols.append(col_remark)
        if col_alias:
            query_cols.append(col_alias)

        cursor.execute(f"SELECT {', '.join(query_cols)} FROM Contact")

        for row in cursor.fetchall():
            username = row[0]
            nickname = row[1] if col_nick else ""
            remark = row[2] if col_remark else ""
            alias = row[3] if col_alias else ""

            display_name = remark or nickname or alias or username
            contacts[username] = {
                "name": display_name,
                "remark": remark,
                "nickname": nickname,
                "alias": alias
            }
        conn.close()
    except Exception as e:
        print(f"[-] Error loading contacts: {str(e)}")
        sys.exit(1)

    print(f"    [+] Loaded {len(contacts)} contacts.")

    contacts[current_user_wxid] = {"name": "Me", "remark": "", "nickname": "Me", "alias": ""}
    contacts["Me"] = {"name": "Me", "remark": "", "nickname": "Me", "alias": ""}

    # 2. Pre-open media DB (one connection for all voice messages)
    media_conn = None
    media_db_path = os.path.join(decrypted_dir, "message_media_0.db")
    if os.path.exists(media_db_path):
        try:
            media_conn = sqlite3.connect(media_db_path)
            print(f"[+] Pre-opened media database for voice message lookup.")
        except Exception as e:
            print(f"[-] Warning: Could not open media DB: {e}")

    # 3. Pre-index media directories (avoid repeated os.walk per message)
    wechat_root = os.path.dirname(wechat_db_dir)
    print("[*] Indexing media directories...")
    video_index = build_dir_index(os.path.join(wechat_root, "msg", "video"))
    file_index = build_dir_index(os.path.join(wechat_root, "msg", "file"))
    print(f"    [+] Indexed {len(video_index)} video files, {len(file_index)} file attachments.")

    # 4. Scan Message Databases
    message_dbs = []
    for file in os.listdir(decrypted_dir):
        if file.startswith("message_message_") and file.endswith(".db"):
            message_dbs.append(os.path.join(decrypted_dir, file))

    if not message_dbs:
        print("[-] No decrypted message databases found (e.g. message_message_0.db).")
        sys.exit(1)

    print(f"[+] Found {len(message_dbs)} message database(s) to parse.")

    # MD5 → username map for resolving message table names
    md5_to_user = {}
    for user in contacts.keys():
        md5_to_user[hashlib.md5(user.encode('utf-8')).hexdigest().lower()] = user

    all_chats = {}
    total_msgs_parsed = 0

    for db_path in message_dbs:
        print(f"[*] Parsing {os.path.basename(db_path)}...")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Name2Id mapping (numeric id → username)
            id_to_name = {}
            try:
                cursor.execute("SELECT rowid, user_name FROM Name2Id")
                for row in cursor.fetchall():
                    id_to_name[row[0]] = row[1]
            except Exception:
                pass

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%';")
            msg_tables = [row[0] for row in cursor.fetchall()]

            for table in msg_tables:
                table_md5 = table[4:].lower()
                talker_user = md5_to_user.get(table_md5)

                if not talker_user:
                    talker_user = f"unknown_{table_md5}"
                    contacts[talker_user] = {
                        "name": f"Unknown ({table_md5[:8]})",
                        "remark": "",
                        "nickname": f"Unknown ({table_md5[:8]})",
                        "alias": ""
                    }

                col_map = get_columns_map(conn, table)
                if not col_map.get("time") or not col_map.get("content"):
                    continue

                select_fields = []
                fields_keys = []
                for k in ["id", "time", "content", "type"]:
                    select_fields.append(col_map.get(k, "NULL"))
                    fields_keys.append(k)
                select_fields.append(col_map.get("real_sender_id", "NULL"))
                fields_keys.append("real_sender_id")
                select_fields.append(col_map.get("is_sender", "NULL"))
                fields_keys.append("is_sender")
                select_fields.append(col_map.get("packed_info", "NULL"))
                fields_keys.append("packed_info")
                select_fields.append(col_map.get("talker", "NULL"))
                fields_keys.append("talker")

                cursor.execute(f"SELECT {', '.join(select_fields)} FROM {table}")

                messages = []
                is_group = talker_user.endswith("@chatroom")

                for row in cursor.fetchall():
                    row_data = dict(zip(fields_keys, row))

                    raw_time = row_data["time"]
                    raw_content = row_data["content"]
                    msg_type = row_data["type"]
                    real_sender_id = row_data["real_sender_id"]
                    is_sender_col = row_data["is_sender"]
                    packed_info = row_data["packed_info"]
                    talker_val = row_data["talker"]

                    if raw_time is None or raw_content is None:
                        continue

                    # Handle seconds vs milliseconds timestamps
                    timestamp = raw_time / 1000.0 if raw_time > 10000000000 else raw_time

                    # Date filtering
                    if since_ts and timestamp < since_ts:
                        continue
                    if until_ts and timestamp >= until_ts:
                        continue

                    dt = datetime.datetime.fromtimestamp(timestamp)
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M:%S")

                    is_sender = 0
                    sender_wxid = None

                    if real_sender_id is not None:
                        sender_wxid = id_to_name.get(real_sender_id)
                        if sender_wxid == current_user_wxid:
                            is_sender = 1
                    elif is_sender_col is not None:
                        is_sender = int(is_sender_col)

                    sender_id = current_user_wxid if is_sender else (sender_wxid or talker_user)
                    msg_content = raw_content

                    if is_group and not is_sender:
                        if sender_wxid:
                            sender_id = sender_wxid
                        elif talker_val and not talker_val.endswith("@chatroom"):
                            sender_id = talker_val

                        # Strip sender prefix from group message content
                        content_to_check = decompress_content(msg_content) if isinstance(msg_content, bytes) else str(msg_content)
                        match = re.match(r"^([a-zA-Z0-9_\-\.]+):\n([\s\S]*)", content_to_check)
                        if match:
                            if not sender_id:
                                sender_id = match.group(1)
                            stripped = match.group(2)
                            msg_content = stripped.encode('utf-8') if isinstance(raw_content, bytes) else stripped

                    display_content = format_message_content(
                        msg_type, msg_content, packed_info,
                        talker_user=talker_user,
                        msg_local_id=row_data["id"],
                        create_time=raw_time,
                        wechat_db_dir=wechat_db_dir,
                        output_dir=output_dir,
                        aes_key=image_aes_key,
                        xor_key=image_xor_key,
                        decrypted_dir=decrypted_dir,
                        trans_cache=trans_cache,
                        voice_language=voice_language,
                        media_conn=media_conn,
                        video_index=video_index,
                        file_index=file_index,
                    )
                    if not display_content:
                        continue

                    sender_name = contacts.get(sender_id, {}).get("name", sender_id)
                    if sender_id == current_user_wxid:
                        sender_name = "Me"

                    text_content = get_message_preview(
                        msg_type, msg_content, packed_info,
                        talker_user=talker_user,
                        msg_local_id=row_data["id"],
                        trans_cache=trans_cache
                    )

                    msg_type_clean = msg_type & 0xffffffff if msg_type is not None else 0
                    messages.append({
                        "timestamp": timestamp,
                        "date_str": date_str,
                        "time_str": time_str,
                        "is_sender": is_sender,
                        "is_system": msg_type == 10000,
                        "is_group": is_group,
                        "is_sticker": msg_type_clean == 47,
                        "sender_name": sender_name,
                        "sender_initial": get_initials(sender_name),
                        "sender_color": get_avatar_color(sender_id),
                        "content": display_content,
                        "text_content": text_content
                    })

                if messages:
                    messages.sort(key=lambda x: x["timestamp"])
                    if talker_user not in all_chats:
                        all_chats[talker_user] = []
                    all_chats[talker_user].extend(messages)
                    total_msgs_parsed += len(messages)

            conn.close()
        except Exception as e:
            print(f"[-] Error parsing message DB: {str(e)}")

    if media_conn:
        media_conn.close()

    print(f"[+] Total messages parsed: {total_msgs_parsed}")

    # 5. Export Chats
    template_dir = os.path.join(project_dir, "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    chat_template = env.get_template("chat.html")
    dashboard_template = env.get_template("dashboard.html")

    dashboard_contacts = []
    contact_filter = args.contact.lower() if args.contact else None

    print("[+] Exporting chat files...")
    exported = 0
    skipped = 0

    for user, messages in all_chats.items():
        messages.sort(key=lambda x: x["timestamp"])

        contact_info = contacts.get(user, {"name": user, "remark": "", "nickname": user, "alias": ""})
        name = contact_info["name"]

        # Contact filter
        if contact_filter and contact_filter not in user.lower() and contact_filter not in name.lower():
            continue

        safe_name = re.sub(r'[\\/*?:"<>|]', "_", name)
        html_filename = f"{safe_name}_{user[:8]}.html"
        txt_filename = f"{safe_name}_{user[:8]}.txt"
        html_path = os.path.join(html_out_dir, html_filename)
        txt_path = os.path.join(txt_out_dir, txt_filename)

        # Incremental mode: skip if HTML already exists
        if args.incremental and os.path.exists(html_path):
            skipped += 1
            last_msg = messages[-1]
            last_preview = html.escape(last_msg["text_content"][:40])
            dashboard_contacts.append({
                "name": name,
                "remark": contact_info["remark"],
                "username": user,
                "html_filename": f"html/{html_filename}",
                "message_count": len(messages),
                "last_message_preview": last_preview,
                "last_message_time": last_msg["date_str"],
                "avatar_color": get_avatar_color(user),
                "initial": get_initials(name)
            })
            continue

        # Render HTML
        rendered_chat = chat_template.render(
            contact_name=name,
            contact_initial=get_initials(name),
            avatar_color=get_avatar_color(user),
            messages=messages
        )
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(rendered_chat)

        # Write TXT
        with open(txt_path, "w", encoding="utf-8") as f:
            for msg in messages:
                if msg["is_system"]:
                    f.write(f"[{msg['date_str']} {msg['time_str']}] {msg['text_content']}\n")
                else:
                    sender = "Me" if msg["is_sender"] else msg["sender_name"]
                    f.write(f"[{msg['date_str']} {msg['time_str']}] {sender}: {msg['text_content']}\n")

        exported += 1
        last_msg = messages[-1]
        last_preview = html.escape(last_msg["text_content"][:40])

        dashboard_contacts.append({
            "name": name,
            "remark": contact_info["remark"],
            "username": user,
            "html_filename": f"html/{html_filename}",
            "message_count": len(messages),
            "last_message_preview": last_preview,
            "last_message_time": last_msg["date_str"],
            "avatar_color": get_avatar_color(user),
            "initial": get_initials(name)
        })

    if args.incremental:
        print(f"    [+] Exported {exported} chats, skipped {skipped} (--incremental).")

    dashboard_contacts.sort(key=lambda x: x["message_count"], reverse=True)

    top_contacts_stats = []
    if dashboard_contacts:
        max_count = dashboard_contacts[0]["message_count"]
        for c in dashboard_contacts[:5]:
            top_contacts_stats.append({
                "name": c["name"],
                "count": c["message_count"],
                "percentage": int((c["message_count"] / max_count) * 100) if max_count > 0 else 0
            })

    export_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rendered_dashboard = dashboard_template.render(
        export_date=export_date,
        total_messages=total_msgs_parsed,
        active_chats=len(all_chats),
        top_contacts=top_contacts_stats,
        contacts=dashboard_contacts
    )

    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(rendered_dashboard)

    # Save transcription cache
    try:
        with open(trans_cache_path, "w", encoding="utf-8") as f:
            json.dump(trans_cache, f, ensure_ascii=False, indent=2)
        print(f"[+] Saved {len(trans_cache)} transcription cache entries.")
    except Exception as e:
        print(f"[-] Error saving transcription cache: {e}")

    # Save failed stickers cache
    try:
        with open(failed_stickers_path, "w", encoding="utf-8") as f:
            json.dump(list(FAILED_STICKERS), f, indent=2)
        print(f"[+] Saved {len(FAILED_STICKERS)} failed sticker cache entries.")
    except Exception as e:
        print(f"[-] Error saving failed stickers cache: {e}")

    print(f"\n[+] EXPORT COMPLETED SUCCESSFULLY!")
    print(f"    [+] HTML Dashboard: {index_path}")
    print(f"    [+] Chat HTML logs: {html_out_dir}")
    print(f"    [+] Chat TXT logs: {txt_out_dir}")


if __name__ == "__main__":
    main()
