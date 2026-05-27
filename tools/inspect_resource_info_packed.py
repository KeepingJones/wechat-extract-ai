import sqlite3

def main():
    conn = sqlite3.connect("decrypted/message_message_resource.db")
    cur = conn.cursor()
    
    cur.execute("SELECT message_id, message_local_id, packed_info FROM MessageResourceInfo WHERE packed_info IS NOT NULL AND length(packed_info) > 0 LIMIT 10")
    rows = cur.fetchall()
    print("Non-empty MessageResourceInfo packed_info:")
    for r in rows:
        print("-" * 50)
        print(f"message_id: {r[0]}, message_local_id: {r[1]}")
        print(f"  hex: {r[2].hex()}")
        print(f"  repr: {repr(r[2])}")
        
    conn.close()

if __name__ == "__main__":
    main()
