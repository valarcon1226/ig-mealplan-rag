import yt_dlp
import os
import tempfile

url = "https://www.instagram.com/p/DMN4ZQROlLo/"

with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
    tmp_path = tmp.name

print(f"Temp file created at {tmp_path}, size: {os.path.getsize(tmp_path)}")

ydl_opts = {
    'outtmpl': tmp_path,
    'quiet': False,
    'no_warnings': False,
}

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    print(f"yt-dlp success! File size: {os.path.getsize(tmp_path)} bytes")
except Exception as e:
    print(f"yt-dlp failed: {e}")
