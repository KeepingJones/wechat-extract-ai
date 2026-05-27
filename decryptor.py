import os
import sys
import json
from Crypto.Cipher import AES

PAGE_SIZE = 4096

def decrypt_file(input_path, output_path, candidate_keys):
    try:
        file_size = os.path.getsize(input_path)
        if file_size == 0:
            return False
            
        with open(input_path, "rb") as f:
            page_1 = f.read(PAGE_SIZE)
            
        if len(page_1) < PAGE_SIZE:
            return False
            
        salt = page_1[:16]
        
        # Test candidate keys
        working_key_bytes = None
        detected_reserve = None
        
        for key_hex in candidate_keys:
            key_bytes = bytes.fromhex(key_hex)
            if len(key_bytes) != 32:
                continue
                
            # Try reserve sizes (80 for SQLCipher 4, 48 for SQLCipher 3)
            for reserve_size in [80, 48]:
                iv_offset = PAGE_SIZE - reserve_size
                iv = page_1[iv_offset : iv_offset + 16]
                ciphertext = page_1[16 : iv_offset]
                
                cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
                decrypted = cipher.decrypt(ciphertext)
                
                if decrypted[:2] == b"\x10\x00":
                    working_key_bytes = key_bytes
                    detected_reserve = reserve_size
                    break
            if working_key_bytes:
                break
                
        if working_key_bytes is None:
            # Check if it is already decrypted (SQLite header starts with "SQLite format 3")
            if page_1.startswith(b"SQLite format 3\0"):
                with open(input_path, "rb") as fin:
                    with open(output_path, "wb") as fout:
                        fout.write(fin.read())
                return True
            return False
            
        # Decrypt page-by-page using the verified key
        with open(input_path, "rb") as fin:
            with open(output_path, "wb") as fout:
                pgno = 1
                while True:
                    page_data = fin.read(PAGE_SIZE)
                    if not page_data:
                        break
                        
                    # Handle page 1 (salt is in first 16 bytes)
                    if pgno == 1:
                        iv_offset = PAGE_SIZE - detected_reserve
                        iv = page_data[iv_offset : iv_offset + 16]
                        ciphertext = page_data[16 : iv_offset]
                        
                        cipher = AES.new(working_key_bytes, AES.MODE_CBC, iv)
                        decrypted = cipher.decrypt(ciphertext)
                        
                        # Reconstruct standard SQLite Page 1:
                        # 16-byte SQLite header + decrypted data + padding
                        decrypted_page = b"SQLite format 3\0" + decrypted + b"\x00" * detected_reserve
                    else:
                        iv_offset = PAGE_SIZE - detected_reserve
                        iv = page_data[iv_offset : iv_offset + 16]
                        ciphertext = page_data[:iv_offset]
                        
                        cipher = AES.new(working_key_bytes, AES.MODE_CBC, iv)
                        decrypted = cipher.decrypt(ciphertext)
                        
                        # Reconstruct standard SQLite Page: decrypted data + padding
                        decrypted_page = decrypted + b"\x00" * detected_reserve
                        
                    fout.write(decrypted_page)
                    pgno += 1
                    
        return True
    except Exception as e:
        print(f"[-] Error decrypting {os.path.basename(input_path)}: {str(e)}")
        return False

def main():
    # Load configuration
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if not os.path.exists(config_path):
        print("[-] config.json not found!")
        sys.exit(1)
        
    with open(config_path, "r") as f:
        config = json.load(f)
        
    wechat_db_dir = config.get("wechat_db_dir", "")
    candidate_keys = config.get("candidate_keys", [])
    
    # Fallback to key field if candidate_keys is empty
    if not candidate_keys and config.get("key"):
        candidate_keys = [config["key"]]
        
    if not wechat_db_dir or not candidate_keys:
        print("[-] Please run key_finder.py first to obtain the keys.")
        sys.exit(1)
        
    # Setup decrypted directory
    decrypted_dir = os.path.join(os.path.dirname(__file__), "decrypted")
    os.makedirs(decrypted_dir, exist_ok=True)
    
    print("[+] Decrypting WeChat databases using candidate keys...")
    
    # We walk through the db_storage directory to decrypt db files
    db_files = []
    for root, dirs, files in os.walk(wechat_db_dir):
        for file in files:
            # Skip WAL, SHM, KVDB, material, FTS files
            if file.endswith(".db") and not any(file.endswith(suffix) for suffix in [".db-wal", ".db-shm", "_fts.db"]):
                db_files.append(os.path.join(root, file))
                
    success_count = 0
    for db_path in db_files:
        rel_path = os.path.relpath(db_path, wechat_db_dir)
        # Avoid subdirectories in names, flatten or preserve structure
        out_name = rel_path.replace(os.sep, "_")
        out_path = os.path.join(decrypted_dir, out_name)
        
        print(f"[*] Decrypting {rel_path} -> decrypted/{out_name}...")
        if decrypt_file(db_path, out_path, candidate_keys):
            print(f"    [+] Decrypted successfully.")
            success_count += 1
        else:
            print(f"    [-] Failed to decrypt (invalid key or format).")
            
    print(f"\n[+] Done. Successfully decrypted {success_count}/{len(db_files)} databases.")
    print("    [!] Note: If you recently logged out or have active chats, please close WeChat cleanly")
    print("        to ensure SQLite Write-Ahead Log (.db-wal) data is committed to the main databases.")

if __name__ == "__main__":
    main()
