import sqlite3
import os
import zstandard as zstd

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
                    text = packed_data[pos : pos + length].decode('utf-8', errors='ignore')
                    text = text.strip()
                    if len(text) > 1 and text.endswith("X") and not text[-2].isalnum():
                        text = text[:-1].strip()
                    return text
    except Exception:
        pass
    return None

def search_in_db(db_path):
    print(f"\nSearching in {db_path}...")
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")
    tables = [r[0] for r in cur.fetchall()]
    
    found_count = 0
    total_voice = 0
    for t in tables:
        # Get columns
        cur.execute(f"PRAGMA table_info({t})")
        cols = [c[1].lower() for c in cur.fetchall()]
        if 'packed_info_data' not in cols:
            continue
            
        cur.execute(f"SELECT local_id, packed_info_data FROM {t} WHERE local_type = 34")
        rows = cur.fetchall()
        for local_id, packed_data in rows:
            total_voice += 1
            if packed_data and len(packed_data) > 4:
                text = extract_voice_trans(packed_data)
                if text:
                    found_count += 1
                    print(f"  Table {t}, local_id {local_id}: \"{text}\" (len of packed={len(packed_data)})")
                    if found_count >= 10:
                        break
        if found_count >= 10:
            break
            
    print(f"Total voice messages checked: {total_voice}, found with trans: {found_count}")
    conn.close()

def main():
    search_in_db("decrypted/message_message_0.db")
    search_in_db("decrypted/message_message_1.db")

if __name__ == "__main__":
    main()
