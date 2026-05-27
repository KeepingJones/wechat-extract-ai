import sqlite3
import os
import zstandard as zstd

def main():
    db_path = "decrypted/message_message_0.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all Msg_ tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")
    tables = [row[0] for row in cursor.fetchall()]
    
    print(f"Total tables: {len(tables)}")
    
    voice_msgs = []
    for table in tables:
        # Check if the table has type column
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [col[1] for col in cursor.fetchall()]
        type_col = None
        for c in cols:
            if c.lower() in ["type", "msgtype", "local_type"]:
                type_col = c
                break
        
        if not type_col:
            continue
            
        cursor.execute(f"SELECT * FROM {table} WHERE {type_col} = 34 LIMIT 5")
        rows = cursor.fetchall()
        if rows:
            for r in rows:
                voice_msgs.append((table, cols, r))
            if len(voice_msgs) >= 20:
                break
                
    print(f"Found {len(voice_msgs)} sample voice messages.")
    for table, cols, r in voice_msgs[:10]:
        print("-" * 50)
        print(f"Table: {table}")
        row_dict = dict(zip(cols, r))
        for k, v in row_dict.items():
            if v is not None:
                # If bytes, print summary/length
                if isinstance(v, bytes):
                    print(f"  {k}: [bytes, length={len(v)}]")
                    if v.startswith(b'\x28\xb5\x2f\xfd'):
                        try:
                            dctx = zstd.ZstdDecompressor()
                            decompressed = dctx.decompress(v)
                            print(f"    Decompressed length: {len(decompressed)}")
                            print(f"    Decompressed text: {decompressed.decode('utf-8', errors='ignore')[:300]}")
                        except Exception as e:
                            print(f"    Decompress error: {e}")
                    else:
                        print(f"    Hex prefix: {v[:30].hex()}")
                        # try decode utf-8
                        try:
                            print(f"    Decoded: {v.decode('utf-8')[:100]}")
                        except:
                            pass
                else:
                    print(f"  {k}: {v}")
                    
    conn.close()

if __name__ == "__main__":
    main()
