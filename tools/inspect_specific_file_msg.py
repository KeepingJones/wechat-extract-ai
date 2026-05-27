import sqlite3
import hashlib
import zstandard as zstd

def main():
    conn_res = sqlite3.connect("decrypted/message_message_resource.db")
    cur_res = conn_res.cursor()
    
    cur_res.execute("SELECT rowid, user_name FROM ChatName2Id")
    chat_map = dict(cur_res.fetchall())
    
    cur_res.execute("SELECT message_id, chat_id, message_local_id, message_svr_id FROM MessageResourceInfo LIMIT 20")
    res_infos = cur_res.fetchall()
    
    conn_msg = sqlite3.connect("decrypted/message_message_0.db")
    cur_msg = conn_msg.cursor()
    
    with open("specific_file_msg.txt", "w", encoding="utf-8") as out:
        for message_id, chat_id, local_id, svr_id in res_infos:
            username = chat_map.get(chat_id)
            if not username:
                continue
            username_md5 = hashlib.md5(username.encode('utf-8')).hexdigest().lower()
            table_name = f"Msg_{username_md5}"
            
            cur_msg.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cur_msg.fetchone():
                continue
                
            cur_msg.execute(f"SELECT message_content, local_type FROM {table_name} WHERE local_id = {local_id}")
            row = cur_msg.fetchone()
            if row:
                content, local_type = row
                if content:
                    if isinstance(content, bytes) and content.startswith(b'\x28\xb5\x2f\xfd'):
                        try:
                            dctx = zstd.ZstdDecompressor()
                            content = dctx.decompress(content)
                        except:
                            pass
                    if isinstance(content, bytes):
                        content = content.decode('utf-8', errors='ignore')
                    out.write("=" * 80 + "\n")
                    out.write(f"Chat: {username}, local_id: {local_id}, svr_id: {svr_id}, local_type: {local_type}\n")
                    out.write(content + "\n")
                    
    conn_res.close()
    conn_msg.close()
    print("Done. Written to specific_file_msg.txt")

if __name__ == "__main__":
    main()
