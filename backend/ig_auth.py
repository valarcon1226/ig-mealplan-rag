"""
ig_auth.py
==========
Manejo centralizado de la sesión de Instagram (instagrapi).

Antes esta lógica vivía duplicada/implícita dentro de ig_recetas.py. Se separa
a su propio módulo para que tanto los endpoints (ig_recetas.py) como la
resolución de media (ig_media.py) puedan reutilizar la misma sesión
persistente sin imports circulares.
"""
import os
from fastapi import HTTPException
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired


def get_client_for_user(username: str = None, password: str = None) -> Client:
    if not username:
        username = os.environ.get("IG_USERNAME")
    if not password:
        password = os.environ.get("IG_PASSWORD")

    if not username:
        raise HTTPException(status_code=400, detail="Debes definir el usuario de Instagram (vía headers X-IG-Username o variables de entorno).")

    user_cl = Client()
    session_path = f"ig_session_{username}.json"

    if os.path.exists(session_path):
        user_cl.load_settings(session_path)
        return user_cl

    if not password:
        raise HTTPException(status_code=401, detail=f"Sesión no iniciada o expirada para {username}, y no se proporcionó contraseña.")

    try:
        user_cl.login(username, password)
        user_cl.dump_settings(session_path)
        return user_cl
    except (LoginRequired, ChallengeRequired) as e:
        raise HTTPException(status_code=401, detail=f"Autenticación de Instagram requerida para {username}: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al iniciar sesión en Instagram para {username}: {str(e)}")
