import os

def list_dir(label, path):
    print(f"\nListing {label} ({path}):")
    if not os.path.exists(path):
        print("Path does not exist")
        return
    try:
        for item in os.listdir(path)[:20]:
            p = os.path.join(path, item)
            print(f"  {'[DIR]' if os.path.isdir(p) else '[FILE]'} {item}")
    except Exception as e:
        print("Error:", e)

def main():
    root = "C:/Users/ewanj/OneDrive/Stuff/Documents/xwechat_files/wxid_y5jo8enhnvdu22_05d2"
    list_dir("msg", os.path.join(root, "msg"))
    list_dir("resource", os.path.join(root, "resource"))
    
    # check for subdirs of msg
    if os.path.exists(os.path.join(root, "msg")):
        for d in os.listdir(os.path.join(root, "msg")):
            if os.path.isdir(os.path.join(root, "msg", d)):
                list_dir(f"msg/{d}", os.path.join(root, "msg", d))

if __name__ == "__main__":
    main()
