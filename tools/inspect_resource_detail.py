import sqlite3
import os

def main():
    conn = sqlite3.connect("decrypted/message_message_resource.db")
    cur = conn.cursor()
    cur.execute("SELECT type, COUNT(*) FROM MessageResourceDetail GROUP BY type")
    types = [r[0] for r in cur.fetchall()]
    
    with open("resource_inspection.txt", "w", encoding="utf-8") as out:
        for t in types:
            cur.execute(f"SELECT * FROM MessageResourceDetail WHERE type = {t} LIMIT 5")
            rows = cur.fetchall()
            out.write("=" * 80 + "\n")
            out.write(f"TYPE: {t} (count = {len(rows)} samples shown)\n")
            for row in rows:
                # Columns: ['resource_id', 'message_id', 'type', 'size', 'create_time', 'access_time', 'status', 'data_index', 'packed_info']
                packed_info = row[8]
                out.write(f"  resource_id: {row[0]}, message_id: {row[1]}, size: {row[3]}, status: {row[6]}\n")
                if packed_info:
                    out.write(f"    packed_info hex: {packed_info.hex()}\n")
                    # Try to parse it
                    # Let's see if we can decode as Protobuf-like tags
                    # Look for 32-character hex or raw bytes that could be MD5
                    out.write(f"    packed_info bytes (escaped): {repr(packed_info)}\n")
                    
    conn.close()
    print("Inspection written to resource_inspection.txt")

if __name__ == "__main__":
    main()
