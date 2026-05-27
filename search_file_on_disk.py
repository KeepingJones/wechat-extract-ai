import os

def main():
    root = "C:/Users/ewanj/OneDrive/Stuff/Documents/xwechat_files/wxid_y5jo8enhnvdu22_05d2/msg/file"
    target = "Kingscollegelondon-graduationprogramme-RFH-Jan2026.pdf"
    
    print(f"Searching for '{target}' in {root}...")
    found = False
    for r, d, f in os.walk(root):
        for filename in f:
            if target.lower() in filename.lower():
                print(f"Found: {os.path.join(r, filename)}")
                found = True
                
    if not found:
        print("Not found.")

if __name__ == "__main__":
    main()
