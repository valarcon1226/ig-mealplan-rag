import cv2
import os
import requests
import tempfile

def extract_end_frame(video_url: str, media_id: str) -> str:
    """
    Descarga el video temporalmente, extrae un frame hacia el final (90%)
    y lo guarda como PNG. Retorna la URL absoluta para el frontend.
    """
    if not video_url:
        return ""
        
    output_dir = "static/thumbnails"
    os.makedirs(output_dir, exist_ok=True)
    
    filename = f"{media_id}.png"
    filepath = os.path.join(output_dir, filename)
    
    if os.path.exists(filepath):
        return f"http://localhost:8001/static/thumbnails/{filename}"
        
    try:
        # 1. Descargar el video a un archivo temporal
        print(f"Downloading video for {media_id}...")
        response = requests.get(video_url, stream=True)
        response.raise_for_status()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            for chunk in response.iter_content(chunk_size=8192):
                tmp.write(chunk)
            temp_path = tmp.name
            
        # 2. Leer el video local con cv2
        cap = cv2.VideoCapture(temp_path)
        if not cap.isOpened():
            os.remove(temp_path)
            return ""
            
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count > 0:
            target_frame = int(frame_count * 0.90)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            
        ret, frame = cap.read()
        cap.release()
        os.remove(temp_path)
        
        if ret:
            cv2.imwrite(filepath, frame)
            return f"http://localhost:8001/static/thumbnails/{filename}"
            
    except Exception as e:
        print(f"Error extracting frame: {e}")
        
    return ""
