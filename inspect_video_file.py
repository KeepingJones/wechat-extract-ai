import os

def main():
    root = "C:/Users/ewanj/OneDrive/Stuff/Documents/xwechat_files/wxid_y5jo8enhnvdu22_05d2/msg"
    
    # Check video folder
    video_dir = os.path.join(root, "video")
    print("Videos:")
    if os.path.exists(video_dir):
        found = False
        for r, d, f in os.walk(video_dir):
            if f:
                print(f"  Folder: {r}")
                for filename in f[:5]:
                    p = os.path.join(r, filename)
                    print(f"    {filename} ({os.path.getsize(p)} bytes)")
                found = True
                break
        if not found:
            print("  No video files found.")
    else:
        print("  Video directory does not exist.")
        
    # Check file folder
    file_dir = os.path.join(root, "file")
    print("\nFiles:")
    if os.path.exists(file_dir):
        found = False
        for r, d, f in os.walk(file_dir):
            if f:
                print(f"  Folder: {r}")
                for filename in f[:5]:
                    p = os.path.join(r, filename)
                    print(f"    {filename} ({os.path.getsize(p)} bytes)")
                found = True
                break
        if not found:
            print("  No document files found.")
    else:
        print("  File directory does not exist.")

if __name__ == "__main__":
    main()
