import sqlite3
import os
import zstandard as zstd
import xml.etree.ElementTree as ET

def main():
    db_path = "decrypted/message_message_0.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")
    tables = [row[0] for row in cursor.fetchall()]
    
    video_msgs = []
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [c[1] for c in cursor.fetchall()]
        
        cursor.execute(f"SELECT * FROM {table} WHERE local_type = 43 LIMIT 5")
        rows = cursor.fetchall()
        if rows:
            for r in rows:
                video_msgs.append((table, cols, r))
            if len(video_msgs) >= 10:
                break
                
    print(f"Found {len(video_msgs)} sample video messages.")
    for table, cols, r in video_msgs[:5]:
        print("-" * 50)
        row_dict = dict(zip(cols, r))
        for k, v in row_dict.items():
            if k in ["message_content", "compress_content", "packed_info_data"] and v:
                if isinstance(v, bytes):
                    if v.startswith(b'\x28\xb5\x2f\xfd'):
                        try:
                            dctx = zstd.ZstdDecompressor()
                            v = dctx.decompress(v)
                        except:
                            pass
                    try:
                        print(f"  {k}: {v.decode('utf-8', errors='ignore')[:300]}")
                    except:
                        print(f"  {k}: [bytes, length={len(v)}]")
                else:
                    print(f"  {k}: {v}")
            elif k in ["local_id", "create_time", "real_sender_id"]:
                print(f"  {k}: {v}")
    conn.close()

if __name__ == "__main__":
    main()
