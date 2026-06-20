import yt_dlp
import requests

def get_shortcode_from_media_id(media_id_str):
    media_id = int(str(media_id_str).split('_')[0])
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    shortcode = ''
    while media_id > 0:
        media_id, remainder = divmod(media_id, 64)
        shortcode = alphabet[remainder] + shortcode
    return shortcode

def download_ig_video(media_id_str, output_path):
    shortcode = get_shortcode_from_media_id(media_id_str)
    url = f"https://www.instagram.com/p/{shortcode}/"
    
    ydl_opts = {
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'overwrites': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def get_ig_image_bytes(media_id_str):
    shortcode = get_shortcode_from_media_id(media_id_str)
    url = f"https://www.instagram.com/p/{shortcode}/"
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        img_url = info.get('thumbnail') or info.get('url')
        
    if not img_url:
        raise ValueError("Could not extract image URL from Instagram")
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    return requests.get(img_url, timeout=30, headers=headers).content
