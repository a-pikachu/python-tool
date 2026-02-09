import os
from opencc import OpenCC

# Simplified → Traditional converter
cc = OpenCC('s2t')

def convert_to_traditional(path):
    if not os.path.isdir(path):
        print(f"Path does not exist or is not a folder: {path}")
        return

    print(f"\nConverting filenames to Traditional Chinese in:\n{path}\n")

    renamed = 0
    for name in os.listdir(path):
        old_path = os.path.join(path, name)

        # Convert Simplified → Traditional
        trad_name = cc.convert(name)

        if trad_name != name:
            new_path = os.path.join(path, trad_name)
            print(f"RENAMING:\n  {name}\n  → {trad_name}\n")
            os.rename(old_path, new_path)
            renamed += 1

    print(f"Done. Renamed {renamed} item(s).")


if __name__ == "__main__":
    folder = input("Enter the folder path: ").strip('"')
    convert_to_traditional(folder)
