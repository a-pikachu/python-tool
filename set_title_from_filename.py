import os
import re
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, ID3NoHeaderError, Encoding, TIT2, TRCK
from mutagen.wave import WAVE
from mutagen.flac import FLAC

# Regex to capture leading "01. " or "1. " or "003. "
TRACK_PREFIX = re.compile(r"^\s*(\d+)\.\s*(.*)$")

def parse_filename(filename):
    """Extract track number and cleaned title from filename."""
    name = os.path.splitext(filename)[0]
    match = TRACK_PREFIX.match(name)

    if match:
        track_num = match.group(1)
        title = match.group(2)
    else:
        track_num = None
        title = name

    return track_num, title

def set_title_and_track(path):
    if not os.path.isdir(path):
        print(f"Invalid folder: {path}")
        return

    print(f"\nSetting Title + Track Number from filenames in:\n{path}\n")

    updated = 0

    for file in os.listdir(path):
        lower = file.lower()
        if not (lower.endswith(".mp3") or lower.endswith(".wav") or lower.endswith(".flac")):
            continue

        full_path = os.path.join(path, file)
        track_num, title = parse_filename(file)

        try:
            # MP3 handling
            if lower.endswith(".mp3"):
                try:
                    tags = ID3(full_path)
                except ID3NoHeaderError:
                    tags = ID3()
                    tags.save(full_path)
                    tags = ID3(full_path)

                tags["TIT2"] = TIT2(encoding=Encoding.UTF8, text=[title])

                if track_num:
                    tags["TRCK"] = TRCK(encoding=Encoding.UTF8, text=[track_num])

                tags.save(full_path)

            # WAV handling
            elif lower.endswith(".wav"):
                try:
                    audio = WAVE(full_path)
                except Exception:
                    print(f"Skipping unreadable WAV: {file}")
                    continue

                try:
                    tags = ID3(full_path)
                except ID3NoHeaderError:
                    tags = ID3()
                    tags.save(full_path)
                    tags = ID3(full_path)

                tags["TIT2"] = TIT2(encoding=Encoding.UTF8, text=[title])

                if track_num:
                    tags["TRCK"] = TRCK(encoding=Encoding.UTF8, text=[track_num])

                tags.save(full_path)

            # FLAC handling
            elif lower.endswith(".flac"):
                audio = FLAC(full_path)
                audio["title"] = title
                if track_num:
                    audio["tracknumber"] = track_num
                audio.save()

            updated += 1
            print(f"UPDATED TAGS:\n  File: {file}\n  Title: {title}\n  Track: {track_num}\n")

        except Exception as e:
            print(f"Error processing {file}: {e}")

    print(f"\nDone. Updated {updated} file(s).")


if __name__ == "__main__":
    folder = input("Enter folder path: ").strip('"')
    set_title_and_track(folder)
