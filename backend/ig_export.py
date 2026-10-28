"""
ig_export.py
============
Lee la exportación oficial de Instagram ("Centro de cuentas -> Tu información ->
Descargar tu información", formato JSON, sección Guardado) y devuelve los posts
guardados con su colección. Así se importa en bloque SIN entrar a la cuenta
(instagrapi hizo que Instagram marcara la cuenta).

La exportación trae (las llaves cambian con el idioma, por eso se lee de forma tolerante):
  your_instagram_activity/saved/saved_posts.json
      {"saved_saved_media": [{"title": "<autor>", "string_map_data": {"Saved on": {"href": url, "timestamp": t}}}]}
  your_instagram_activity/saved/saved_collections.json
      {"saved_saved_collections": [
          {"title": "Collection", "string_map_data": {"Name": {"value": "recetas"}, ...}},   <- encabezado
          {"title": "<autor>", "string_map_data": {"Name": {"href": url, "value": "<autor>"}, "Added Time": {...}}},
          ...]}
"""
import io
import json
import re
import zipfile
from typing import Any, Dict, List, Optional

_POST_RE = re.compile(r"instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def shortcode_to_pk(shortcode: str) -> str:
    """Inverso de ig_downloader.get_shortcode_from_media_id: el pk es la 1a parte del media_id."""
    pk = 0
    for ch in shortcode:
        pk = pk * 64 + _ALPHABET.index(ch)
    return str(pk)


def _fields(entry: dict) -> List[dict]:
    smd = entry.get("string_map_data") or {}
    return [v for v in smd.values() if isinstance(v, dict)]


def _entry_post(entry: dict) -> Optional[Dict[str, Any]]:
    """Si la entrada es un post guardado: {shortcode, url, username, saved_at}."""
    href = next((f["href"] for f in _fields(entry) if isinstance(f.get("href"), str)), None)
    m = _POST_RE.search(href or "")
    if not m:
        return None
    ts = next((f["timestamp"] for f in _fields(entry) if isinstance(f.get("timestamp"), int) and f["timestamp"]), None)
    author = entry.get("title") or next((f.get("value") for f in _fields(entry) if f.get("value")), None)
    return {"shortcode": m.group(1), "url": f"https://www.instagram.com/p/{m.group(1)}/",
            "username": author, "saved_at": ts}


def _entry_collection_name(entry: dict) -> Optional[str]:
    """Encabezado de colección: sin enlace, con un nombre ("Name"/"Nombre" -> value)."""
    if _entry_post(entry):
        return None
    return next((f["value"] for f in _fields(entry) if isinstance(f.get("value"), str) and f["value"].strip()), None)


def _lists(data: Any):
    """Listas de entradas dentro del JSON (la llave raíz cambia: saved_saved_media, ...)."""
    if isinstance(data, list):
        yield data
    elif isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                yield v


def parse_saved_json(data: Any, in_collections: bool) -> List[Dict[str, Any]]:
    posts = []
    for entries in _lists(data):
        current = None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            post = _entry_post(entry)
            if post:
                posts.append({**post, "collection": current if in_collections else None})
            elif in_collections:
                current = _entry_collection_name(entry) or current
    return posts


def parse_export(content: bytes, filename: str) -> List[Dict[str, Any]]:
    """
    Acepta el ZIP completo de la exportación o los JSON sueltos. Un post que está en una
    colección queda con esa colección (gana sobre "sin colección").
    """
    files = []  # (nombre, json)
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for name in z.namelist():
                if name.lower().endswith(".json") and "saved" in name.lower():
                    files.append((name, json.loads(z.read(name).decode("utf-8"))))
    else:
        files.append((filename, json.loads(content.decode("utf-8"))))
    if not files:
        raise ValueError("No encontré los guardados en el archivo. Exporta en formato JSON e incluye la sección 'Guardado'.")

    by_code: Dict[str, Dict[str, Any]] = {}
    for name, data in files:
        is_collections = "collection" in name.lower() or (isinstance(data, dict) and any("collection" in k for k in data))
        for post in parse_saved_json(data, is_collections):
            prev = by_code.get(post["shortcode"])
            if not prev or (post["collection"] and not prev["collection"]):
                by_code[post["shortcode"]] = post
    return list(by_code.values())


if __name__ == "__main__":
    # python ig_export.py
    from ig_downloader import get_shortcode_from_media_id
    assert get_shortcode_from_media_id(shortcode_to_pk("DYhufPApGzD") + "_123") == "DYhufPApGzD"

    saved = {"saved_saved_media": [
        {"title": "chef_a", "string_map_data": {"Saved on": {"href": "https://www.instagram.com/reel/AAA111/", "timestamp": 1700000000}}},
        {"title": "chef_b", "string_map_data": {"Guardado el": {"href": "https://www.instagram.com/p/BBB222/", "timestamp": 1700000100}}},
    ]}
    cols = {"saved_saved_collections": [
        {"title": "Collection", "string_map_data": {"Name": {"value": "recetas saludables"}, "Creation Time": {"timestamp": 1}}},
        {"title": "chef_a", "string_map_data": {"Name": {"href": "https://www.instagram.com/reel/AAA111/", "value": "chef_a"}, "Added Time": {"timestamp": 2}}},
        {"title": "Colección", "string_map_data": {"Nombre": {"value": "postres"}}},
        {"title": "chef_c", "string_map_data": {"Nombre": {"href": "https://www.instagram.com/p/CCC333/", "value": "chef_c"}}},
    ]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("your_instagram_activity/saved/saved_posts.json", json.dumps(saved))
        z.writestr("your_instagram_activity/saved/saved_collections.json", json.dumps(cols))
    got = {p["shortcode"]: p for p in parse_export(buf.getvalue(), "export.zip")}
    assert set(got) == {"AAA111", "BBB222", "CCC333"}, got
    assert got["AAA111"]["collection"] == "recetas saludables" and got["AAA111"]["username"] == "chef_a"
    assert got["BBB222"]["collection"] is None and got["BBB222"]["saved_at"] == 1700000100
    assert got["CCC333"]["collection"] == "postres"
    assert parse_export(json.dumps(saved).encode(), "saved_posts.json")[0]["shortcode"] == "AAA111"
    print("ok")
