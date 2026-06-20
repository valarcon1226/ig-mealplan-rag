import subprocess

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
print(f"Shortcode: {shortcode}")
url = f"https://www.instagram.com/p/{shortcode}/"
print(f"URL: {url}")

try:
    subprocess.run(["yt-dlp", url, "-o", "test_video.mp4"], check=True)
    print("yt-dlp succeeded!")
except Exception as e:
    print(f"yt-dlp failed: {e}")
