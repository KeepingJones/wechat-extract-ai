import sqlite3

def main():
    conn = sqlite3.connect("decrypted/message_message_resource.db")
    cur = conn.cursor()
    cur.execute("SELECT type, COUNT(*) FROM MessageResourceDetail GROUP BY type")
    types = [r[0] for r in cur.fetchall()]
    
    for t in types:
        cur.execute(f"SELECT * FROM MessageResourceDetail WHERE type = {t} LIMIT 1")
        row = cur.fetchone()
        if row:
            # Columns: ['resource_id', 'message_id', 'type', 'size', 'create_time', 'access_time', 'status', 'data_index', 'packed_info']
            packed_info = row[8]
            print("=" * 60)
            print(f"Type: {t}, Size: {row[3]}, Status: {row[6]}")
            if packed_info:
                print(f"  packed_info hex: {packed_info[:40].hex()}")
                print(f"  packed_info ascii: {packed_info.decode('ascii', errors='ignore')[:100]}")
                print(f"  packed_info utf-8: {packed_info.decode('utf-8', errors='ignore')[:100]}")
    conn.close()

if __name__ == "__main__":
    main()
