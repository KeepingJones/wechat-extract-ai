import sqlite3
import os
import zstandard as zstd

def main():
    db_path = "decrypted/message_message_0.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")
    tables = [row[0] for row in cursor.fetchall()]
    
    app_msgs = []
    for table in tables:
        cursor.execute(f"SELECT local_id, create_time, message_content, local_type FROM {table}")
        rows = cursor.fetchall()
        for r in rows:
            local_id, ts, content, local_type = r
            if local_type is not None and (local_type & 0xffffffff) == 49:
                if content:
                    if isinstance(content, bytes) and content.startswith(b'\x28\xb5\x2f\xfd'):
                        try:
                            dctx = zstd.ZstdDecompressor()
                            content = dctx.decompress(content)
                        except:
                            pass
                    if isinstance(content, bytes):
                        content = content.decode('utf-8', errors='ignore')
                    app_msgs.append((table, local_id, ts, content))
                    if len(app_msgs) >= 20:
                        break
        if len(app_msgs) >= 20:
            break
            
    print(f"Found {len(app_msgs)} app messages.")
    with open("files_inspection.txt", "w", encoding="utf-8") as out:
        for table, local_id, ts, content in app_msgs:
            out.write("=" * 80 + "\n")
            out.write(f"Table: {table}, local_id: {local_id}, ts: {ts}\n")
            out.write(content + "\n")
            
    conn.close()
    print("Written to files_inspection.txt")

if __name__ == "__main__":
    main()
