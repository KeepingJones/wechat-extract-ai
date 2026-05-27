import sqlite3
import os

def inspect_db(name, path):
    print(f"\n===== Inspecting {name} ({path}) =====")
    if not os.path.exists(path):
        print("File does not exist.")
        return
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print("Tables:", tables)
    for t in tables[:10]:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [c[1] for c in cur.fetchall()]
        print(f"\nTable: {t}")
        print(f"Columns: {cols}")
        try:
            cur.execute(f"SELECT * FROM {t} LIMIT 3")
            rows = cur.fetchall()
            for r in rows:
                print("  Row:", r[:5], "... (len={})".format(len(r)))
        except Exception as e:
            print("  Error reading rows:", e)
    conn.close()

def main():
    inspect_db("media_0", "decrypted/message_media_0.db")
    inspect_db("message_resource", "decrypted/message_message_resource.db")

if __name__ == "__main__":
    main()
