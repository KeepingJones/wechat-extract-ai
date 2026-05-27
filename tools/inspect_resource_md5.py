import sqlite3

def main():
    conn = sqlite3.connect("decrypted/message_message_resource.db")
    cur = conn.cursor()
    
    # Let's query MessageResourceDetail rows where packed_info is not null and length > 0
    cur.execute("SELECT resource_id, message_id, type, size, packed_info FROM MessageResourceDetail WHERE packed_info IS NOT NULL AND length(packed_info) > 0 LIMIT 10")
    rows = cur.fetchall()
    print("Non-empty MessageResourceDetail packed_info:")
    for r in rows:
        print(f"  resource_id: {r[0]}, message_id: {r[1]}, type: {r[2]}, size: {r[3]}")
        print(f"    hex: {r[4].hex()}")
        print(f"    repr: {repr(r[4])}")
        
    # Let's query MessageResourceInfo rows where packed_info is not null and length > 0
    cur.execute("SELECT message_id, local_id, packed_info FROM MessageResourceInfo WHERE packed_info IS NOT NULL AND length(packed_info) > 0 LIMIT 10")
    rows = cur.fetchall()
    print("\nNon-empty MessageResourceInfo packed_info:")
    for r in rows:
        print(f"  message_id: {r[0]}, local_id: {r[1]}")
        print(f"    hex: {r[2].hex()}")
        print(f"    repr: {repr(r[2])}")
        
    conn.close()

if __name__ == "__main__":
    main()
