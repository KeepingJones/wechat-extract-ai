import sqlite3
import os

def main():
    db_path = "decrypted/message_message_resource.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM MessageResourceDetail LIMIT 10")
    rows = cur.fetchall()
    
    # Columns: ['resource_id', 'message_id', 'type', 'size', 'create_time', 'access_time', 'status', 'data_index', 'packed_info']
    print("MessageResourceDetail:")
    for r in rows:
        packed_info = r[8]
        print("-" * 50)
        print(f"resource_id: {r[0]}, message_id: {r[1]}, type: {r[2]}, size: {r[3]}, status: {r[6]}, data_index: {r[7]}")
        if packed_info:
            print(f"  packed_info (len={len(packed_info)}): {packed_info[:40].hex()}")
            # print printable characters or see if md5 is in it
            try:
                # search for 32-char hex or MD5
                # MD5 is often 16 bytes raw or 32 chars hex text
                print(f"  as ascii: {packed_info.decode('ascii', errors='ignore')}")
            except:
                pass
                
    cur.execute("SELECT * FROM MessageResourceInfo LIMIT 10")
    rows = cur.fetchall()
    # Columns: ['message_id', 'chat_id', 'sender_id', 'message_local_type', 'message_create_time', 'message_local_id', 'message_svr_id', 'message_origin_source', 'packed_info']
    print("\nMessageResourceInfo:")
    for r in rows:
        packed_info = r[8]
        print("-" * 50)
        print(f"message_id: {r[0]}, chat_id: {r[1]}, sender_id: {r[2]}, local_id: {r[5]}, svr_id: {r[6]}")
        if packed_info:
            print(f"  packed_info (len={len(packed_info)}): {packed_info[:40].hex()}")
            try:
                print(f"  as ascii: {packed_info.decode('ascii', errors='ignore')}")
            except:
                pass
                
    conn.close()

if __name__ == "__main__":
    main()
