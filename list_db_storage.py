import os
import json

def main():
    config_path = "config.json"
    with open(config_path, "r") as f:
        config = json.load(f)
    db_dir = config["wechat_db_dir"]
    print(f"Listing db_storage: {db_dir}")
    for root, dirs, files in os.walk(db_dir):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, db_dir)
            size = os.path.getsize(p)
            print(f"  {rel} ({size} bytes)")

if __name__ == "__main__":
    main()
