import sqlite3
import os

def main():
    db_path = "decrypted/message_media_0.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(VoiceInfo)")
    cols = [c[1] for c in cursor.fetchall()]
    print("VoiceInfo Columns:", cols)
    
    cursor.execute("SELECT * FROM VoiceInfo LIMIT 10")
    rows = cursor.fetchall()
    print(f"Total sample rows: {len(rows)}")
    for r in rows:
        row_dict = dict(zip(cols, r))
        print("-" * 50)
        for k, v in row_dict.items():
            if k == "voice_data":
                print(f"  voice_data: [bytes, length={len(v)}], hex prefix={v[:30].hex()}")
            else:
                print(f"  {k}: {v}")
    conn.close()

if __name__ == "__main__":
    main()
