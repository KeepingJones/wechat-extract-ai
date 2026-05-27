import os

def main():
    path = "C:/Users/ewanj/OneDrive/Stuff/Documents/xwechat_files/wxid_y5jo8enhnvdu22_05d2"
    print(f"Listing {path}:")
    try:
        items = os.listdir(path)
        for item in items:
            p = os.path.join(path, item)
            is_dir = os.path.isdir(p)
            print(f"  {'[DIR]' if is_dir else '[FILE]'} {item}")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
