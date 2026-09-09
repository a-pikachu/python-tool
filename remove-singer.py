import os
import re

def clean_filenames(folder):
    # Remove anything inside square brackets: [張柏芝]
    pattern = re.compile("\[[^]]+\]")

    for filename in os.listdir(folder):
        old_path = os.path.join(folder, filename)

        if not os.path.isfile(old_path):
            continue

        new_name = pattern.sub("", filename).strip()

        # Remove double spaces created after deletion
        new_name = re.sub(" {2,}", " ", new_name)

        new_path = os.path.join(folder, new_name)

        print(f"Renaming:\n  {filename}\n→ {new_name}\n")
        os.rename(old_path, new_path)


if __name__ == "__main__":
    folder = input("Enter folder path: ").strip()
    clean_filenames(folder)
