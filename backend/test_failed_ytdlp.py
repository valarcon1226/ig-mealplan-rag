import yt_dlp
import os

media_id = "3678844496692007656"
alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
m_id = int(media_id)
shortcode = ''
while m_id > 0:
    m_id, remainder = divmod(m_id, 64)
    shortcode = alphabet[remainder] + shortcode

url = f"https://www.instagram.com/p/{shortcode}/"
print(f"URL: {url}")

ydl_opts = {
    'outtmpl': 'test_video.mp4',
    'quiet': False,
    'no_warnings': False,
}

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    print("yt-dlp success!")
    if os.path.exists("test_video.mp4"):
        print(f"File size: {os.path.getsize('test_video.mp4')} bytes")
except Exception as e:
    print(f"yt-dlp failed: {e}")
