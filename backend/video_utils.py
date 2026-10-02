import cv2
import os
import requests
import tempfile

def save_remote_image(url: str, media_id: str) -> str:
    """
    Guarda localmente una imagen remota (p. ej. la portada de un post de foto).
    Las URLs del CDN de Instagram caducan, así que nunca se guarda la URL tal cual.
    Devuelve la ruta relativa o "" si la URL no es una imagen o falla la descarga.
    """
    if not url:
        return ""
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok and resp.headers.get("Content-Type", "").startswith("image/"):
            os.makedirs("static/thumbnails", exist_ok=True)
            filename = f"{media_id}.jpg"
            with open(os.path.join("static/thumbnails", filename), "wb") as f:
                f.write(resp.content)
            return f"/static/thumbnails/{filename}"
    except requests.RequestException as e:
        print(f"Error saving image for {media_id}: {e}")
    return ""


def extract_end_frame(video_url: str, media_id: str, local_video_path: str = None, target_timestamp: float = None) -> str:
    """
    Extrae un frame específico de un video usando OpenCV.
    Si se provee local_video_path, lo usa directamente. Si no, descarga temporalmente el video_url.
    Si se provee target_timestamp, extrae ese segundo. Si no, extrae al 90%.
    """
    if not video_url and not local_video_path:
        return ""
        
    output_dir = "static/thumbnails"
    os.makedirs(output_dir, exist_ok=True)
    
    filename = f"{media_id}.png"
    filepath = os.path.join(output_dir, filename)
    
    if os.path.exists(filepath):
        return f"/static/thumbnails/{filename}"  # relativa: el frontend la reenvía al backend
        
    temp_path = local_video_path
    cleanup_temp = False
    
    try:
        if not temp_path:
            # Descargar el video a un archivo temporal
            print(f"Downloading video for {media_id}...")
            from ig_downloader import download_ig_video
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                temp_path = tmp.name
                cleanup_temp = True
                
            download_ig_video(media_id, temp_path)
            
        # Leer el video local con cv2
        cap = cv2.VideoCapture(temp_path)
        if not cap.isOpened():
            if cleanup_temp and os.path.exists(temp_path):
                os.remove(temp_path)
            return ""
            
        if target_timestamp is not None and target_timestamp >= 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, target_timestamp * 1000)
        else:
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if frame_count > 0:
                target_frame = int(frame_count * 0.90)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            
        ret, frame = cap.read()
        cap.release()
        
        if cleanup_temp and os.path.exists(temp_path):
            os.remove(temp_path)
        
        if ret:
            cv2.imwrite(filepath, frame)
            return f"/static/thumbnails/{filename}"  # relativa: el frontend la reenvía al backend
            
    except Exception as e:
        print(f"Error extracting frame: {e}")
        
    return ""
