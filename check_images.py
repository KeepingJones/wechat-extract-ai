import os

def main():
    root = "C:/Users/ewanj/OneDrive/Stuff/Documents/xwechat_files/wxid_y5jo8enhnvdu22_05d2/msg/attach"
    if not os.path.exists(root):
        print("Root does not exist")
        return
        
    found_any = False
    for r, d, f in os.walk(root):
        # find folders named 'Img'
        if os.path.basename(r) == "Img" and f:
            print(f"\nFound Img folder: {r}")
            print(f"Files inside ({len(f)} files):")
            for filename in f[:5]:
                p = os.path.join(r, filename)
                size = os.path.getsize(p)
                with open(p, "rb") as file_bytes:
                    head = file_bytes.read(16)
                print(f"  {filename} ({size} bytes), hex prefix={head.hex()}")
            found_any = True
            break
            
    if not found_any:
        print("No Img files found.")

if __name__ == "__main__":
    main()
