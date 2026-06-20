import yt_dlp

def get_shortcode_from_media_id(media_id_str):
    media_id = int(media_id_str.split('_')[0])
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    shortcode = ''
    while media_id > 0:
        media_id, remainder = divmod(media_id, 64)
        shortcode = alphabet[remainder] + shortcode
    return shortcode

media_id = "3703676933956579368_3017657735"
shortcode = get_shortcode_from_media_id(media_id)
url = f"https://www.instagram.com/p/{shortcode}/"

ydl_opts = {
    'outtmpl': 'test_video.mp4',
    'quiet': True,
    'no_warnings': True,
}

print(f"Downloading from {url}")
try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    print("yt-dlp python success!")
except Exception as e:
    print(f"yt-dlp python failed: {e}")
