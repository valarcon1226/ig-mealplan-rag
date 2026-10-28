"""Self-check de cuentas: registro, login, datos por usuario y logout. Correr: python test_auth.py"""
import secrets
from fastapi.testclient import TestClient

from ig_recetas import app, hash_password, verify_password
from database import SessionLocal
from models import User, AuthSession

h = hash_password("clave-segura")
assert verify_password("clave-segura", h) and not verify_password("otra", h)

c = TestClient(app)
email = f"test-{secrets.token_hex(4)}@example.com"
try:
    r = c.post("/auth/register", json={"name": "Test", "email": email.upper(), "password": "12345678"})
    assert r.status_code == 200, r.text
    assert c.post("/auth/register", json={"name": "Test", "email": email, "password": "12345678"}).status_code == 409
    assert c.post("/auth/register", json={"name": "T", "email": "malo", "password": "12345678"}).status_code == 400
    assert c.post("/auth/register", json={"name": "T", "email": "a" + email, "password": "corta"}).status_code == 400

    assert c.post("/auth/login", json={"email": email, "password": "incorrecta"}).status_code == 401
    r = c.post("/auth/login", json={"email": email, "password": "12345678"})
    assert r.status_code == 200 and r.json()["user"]["name"] == "Test"
    auth = {"Authorization": f"Bearer {r.json()['token']}"}

    assert c.get("/me/data").status_code == 401
    assert c.get("/me/data", headers=auth).json()["data"] is None
    payload = {"profile": {"age": 30}, "recipes": [{"id": "1", "title": "Ají de gallina"}], "eatLog": []}
    assert c.put("/me/data", json=payload, headers=auth).status_code == 200
    assert c.get("/me/data", headers=auth).json()["data"] == payload

    assert c.post("/auth/logout", headers=auth).status_code == 200
    assert c.get("/me/data", headers=auth).status_code == 401
    print("test_auth OK")
finally:
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    if user:
        db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
        db.delete(user)
        db.commit()
    db.close()
