import os

def main():
    root = "C:/Users/ewanj/OneDrive/Stuff/Documents/xwechat_files/wxid_y5jo8enhnvdu22_05d2/msg/attach"
    if not os.path.exists(root):
        print("Root does not exist")
        return
        
    subdirs = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    print(f"Total MD5 attach directories: {len(subdirs)}")
    
    # List the first 5 subdirs and their children
    for sd in subdirs[:5]:
        p = os.path.join(root, sd)
        print(f"\nFolder: {sd}")
        for item in os.listdir(p)[:10]:
            ip = os.path.join(p, item)
            is_dir = os.path.isdir(ip)
            print(f"  {'[DIR]' if is_dir else '[FILE]'} {item}")
            if is_dir:
                for subitem in os.listdir(ip)[:5]:
                    print(f"    - {subitem}")

if __name__ == "__main__":
    main()
