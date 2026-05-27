import os
import re
import sys
import json
import ctypes
from ctypes import wintypes
from Crypto.Cipher import AES

# Windows process Snapshot constants
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

# Memory page constants
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260)
    ]

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("__alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("__alignment2", wintypes.DWORD),
    ]

# Setup kernel32 functions
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t

kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t)
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL

def get_pids_by_name(process_names):
    pids = []
    hSnapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if hSnapshot == -1:
        return pids
    
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    
    retval = kernel32.Process32FirstW(hSnapshot, ctypes.byref(pe))
    while retval:
        if pe.szExeFile.lower() in process_names:
            pids.append((pe.szExeFile, pe.th32ProcessID))
        retval = kernel32.Process32NextW(hSnapshot, ctypes.byref(pe))
        
    kernel32.CloseHandle(hSnapshot)
    return pids

def read_memory(hProcess, address, size):
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    success = kernel32.ReadProcessMemory(
        hProcess,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(bytes_read)
    )
    if success:
        return buffer.raw[:bytes_read.value]
    return None

def verify_key_on_any(key_hex, db_paths):
    # Test key against a list of databases to see if it decrypts any of them
    try:
        key_bytes = bytes.fromhex(key_hex)
        if len(key_bytes) != 32:
            return False
            
        for db_path in db_paths:
            if not os.path.exists(db_path):
                continue
            with open(db_path, "rb") as f:
                page_1 = f.read(4096)
            if len(page_1) < 4096:
                continue
                
            for reserve_size in [80, 48]:
                iv_offset = 4096 - reserve_size
                iv = page_1[iv_offset : iv_offset + 16]
                ciphertext = page_1[16 : iv_offset]
                
                cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
                decrypted = cipher.decrypt(ciphertext)
                
                if decrypted[:2] == b"\x10\x00":
                    return True
    except Exception:
        pass
    return False

def scan_process_memory(pid, test_db_paths):
    hProcess = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not hProcess:
        print(f"[-] Access Denied: Cannot open process PID {pid}. Please run as Administrator!")
        return []
        
    print(f"[+] Scanning memory of process PID {pid}...")
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0
    
    # Specific SQLCipher pattern: x'...'
    pattern_ascii = re.compile(rb"x\'([0-9a-fA-F]{64})\'")
    pattern_utf16 = re.compile(rb"x\x00\'\x00((?:[0-9a-fA-F]\x00){64})\'\x00")
    
    pattern_ascii_salt = re.compile(rb"x\'([0-9a-fA-F]{96})\'")
    pattern_utf16_salt = re.compile(rb"x\x00\'\x00((?:[0-9a-fA-F]\x00){96})\'\x00")
    
    # Standalone hex keys
    pattern_standalone_ascii = re.compile(rb"\b([0-9a-fA-F]{64})\b")
    pattern_standalone_utf16 = re.compile(rb"\b((?:[0-9a-fA-F]\x00){64})\b")
    
    valid_keys = set()
    tested = set()
    
    while kernel32.VirtualQueryEx(hProcess, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)) > 0:
        # Commit state, not guarded, readable/writeable
        if mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_GUARD) and not (mbi.Protect & PAGE_NOACCESS):
            chunk = read_memory(hProcess, address, mbi.RegionSize)
            if chunk:
                # Local helper to test and add keys
                def try_add_key(key):
                    if key not in tested:
                        tested.add(key)
                        # We verify if this key decrypts at least one of our databases
                        if verify_key_on_any(key, test_db_paths):
                            valid_keys.add(key)
                            print(f"    [+] Found valid key: {key[:8]}...{key[-8:]}")
                
                # 1. Search for x'...' patterns
                for match in pattern_ascii.finditer(chunk):
                    try_add_key(match.group(1).decode('ascii').lower())
                            
                for match in pattern_utf16.finditer(chunk):
                    try_add_key(match.group(1).replace(b"\x00", b"").decode('ascii').lower())

                for match in pattern_ascii_salt.finditer(chunk):
                    try_add_key(match.group(1)[:64].decode('ascii').lower())

                for match in pattern_utf16_salt.finditer(chunk):
                    try_add_key(match.group(1)[:128].replace(b"\x00", b"").decode('ascii').lower()[:64])

                # 2. Search for standalone hex keys (fallback)
                for match in pattern_standalone_ascii.finditer(chunk):
                    try_add_key(match.group(1).decode('ascii').lower())
                            
                for match in pattern_standalone_utf16.finditer(chunk):
                    try_add_key(match.group(1).replace(b"\x00", b"").decode('ascii').lower())
                            
        address += mbi.RegionSize
        
    kernel32.CloseHandle(hProcess)
    return list(valid_keys)

def main():
    # Load configuration
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if not os.path.exists(config_path):
        print("[-] config.json not found! Run from the project directory.")
        sys.exit(1)
        
    with open(config_path, "r") as f:
        config = json.load(f)
        
    wechat_db_dir = config.get("wechat_db_dir", "")
    if not wechat_db_dir:
        print("[-] Please configure 'wechat_db_dir' in config.json first.")
        sys.exit(1)
        
    # We will gather a few databases to test against
    test_db_paths = [
        os.path.join(wechat_db_dir, "contact", "contact.db"),
        os.path.join(wechat_db_dir, "message", "message_0.db"),
        os.path.join(wechat_db_dir, "message", "message_1.db"),
        os.path.join(wechat_db_dir, "message", "message_resource.db"),
        os.path.join(wechat_db_dir, "message", "media_0.db")
    ]
        
    # Get PIDs of WeChat or Weixin
    targets = ["weixin.exe", "wechat.exe"]
    pids = get_pids_by_name(targets)
    if not pids:
        print("[-] WeChat/Weixin process not found! Please open WeChat and log in.")
        sys.exit(1)
        
    all_found_keys = []
    for name, pid in pids:
        print(f"[+] Found process: {name} (PID: {pid})")
        keys = scan_process_memory(pid, test_db_paths)
        if keys:
            all_found_keys.extend(keys)
            
    # De-duplicate keys
    all_found_keys = list(set(all_found_keys))
            
    if all_found_keys:
        print(f"[+] SUCCESS! Found {len(all_found_keys)} verified keys in memory.")
        config["candidate_keys"] = all_found_keys
        # Keep the first key as default
        config["key"] = all_found_keys[0]
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print("[+] Keys saved to config.json.")
    else:
        print("[-] No verified keys found in process memory.")
        print("    Ensure WeChat is logged in and you ran this script as Administrator.")
        sys.exit(1)

if __name__ == "__main__":
    main()
