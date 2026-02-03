
import os
from datetime import datetime

def get_photo_search_paths():
    paths = []
    onedrive_path = os.environ.get("OneDrive", os.path.expanduser("~\\OneDrive"))
    user_home = os.path.expanduser("~")
    
    potential_roots = [
        "D:\\WANGBIAO",
        onedrive_path,
        os.path.join(user_home, "OneDrive"),
        user_home
    ]
    
    subdirs = [
        os.path.join("Pictures", "本机照片"),
        os.path.join("图片", "本机照片"),
        "本机照片"
    ]
    
    for root in potential_roots:
        if root and os.path.exists(root):
            for sub in subdirs:
                p = os.path.join(root, sub)
                if os.path.exists(p):
                    paths.append(p)
    return list(set([os.path.abspath(p) for p in paths]))

def scan_first_few():
    paths = get_photo_search_paths()
    print(f"Search Paths: {paths}")
    count = 0
    for search_path in paths:
        for root, dirs, files in os.walk(search_path):
            for file in files:
                if file.startswith("photo_") and file.endswith(".jpg"):
                    print(f"FOUND: {os.path.join(root, file)}")
                    count += 1
                    if count >= 3: return

if __name__ == "__main__":
    scan_first_few()
