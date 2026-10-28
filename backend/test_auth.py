"""Self-check de cuentas: registro, login, datos por usuario y logout. Correr: python test_auth.py o pytest test_auth.py"""
import secrets
from fastapi.testclient import TestClient

from ig_recetas import app, hash_password, verify_password
from database import SessionLocal
from models import User, AuthSession, PantryItem


def test_password_hashing():
    h = hash_password("clave-segura")
    assert verify_password("clave-segura", h) and not verify_password("otra", h)


def test_auth_and_user_data():
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
    finally:
        db = SessionLocal()
        user = db.query(User).filter(User.email == email).first()
        if user:
            db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
            db.delete(user)
            db.commit()
        db.close()


def test_pantry_isolation_and_auth():
    c = TestClient(app)

    # 1. Sin token da 401
    assert c.get("/api/pantry").status_code == 401
    assert c.post("/api/pantry", json={"name": "Arroz"}).status_code == 401
    assert c.delete("/api/pantry/1").status_code == 401

    email_a = f"test-a-{secrets.token_hex(4)}@example.com"
    email_b = f"test-b-{secrets.token_hex(4)}@example.com"
    try:
        # Registrar e iniciar sesión como usuario A
        res_a = c.post("/auth/register", json={"name": "User A", "email": email_a, "password": "password123"})
        assert res_a.status_code == 200
        token_a = res_a.json()["token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # Registrar e iniciar sesión como usuario B
        res_b = c.post("/auth/register", json={"name": "User B", "email": email_b, "password": "password123"})
        assert res_b.status_code == 200
        token_b = res_b.json()["token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # 2. Usuario A crea item de despensa
        item_name = f"Arroz-{secrets.token_hex(3)}"
        res_create = c.post("/api/pantry", json={"name": item_name, "amount": "1 kg"}, headers=headers_a)
        assert res_create.status_code == 200, res_create.text
        item_a = res_create.json()
        assert item_a["name"] == item_name
        item_a_id = item_a["id"]

        # Usuario A sí ve su item
        pantry_a = c.get("/api/pantry", headers=headers_a).json()
        assert any(it["id"] == item_a_id for it in pantry_a)

        # 3. Usuario B no lo ve en GET /api/pantry
        pantry_b = c.get("/api/pantry", headers=headers_b).json()
        assert not any(it["id"] == item_a_id or it["name"] == item_name for it in pantry_b)

        # 4. Usuario B intenta borrar el item de A -> devuelve 404
        assert c.delete(f"/api/pantry/{item_a_id}", headers=headers_b).status_code == 404

        # 5. Usuario A sí puede borrar su propio item
        assert c.delete(f"/api/pantry/{item_a_id}", headers=headers_a).status_code == 200
    finally:
        db = SessionLocal()
        for em in (email_a, email_b):
            u = db.query(User).filter(User.email == em).first()
            if u:
                db.query(PantryItem).filter(PantryItem.user_id == u.id).delete()
                db.query(AuthSession).filter(AuthSession.user_id == u.id).delete()
                db.delete(u)
        db.commit()
        db.close()


if __name__ == "__main__":
    test_password_hashing()
    test_auth_and_user_data()
    test_pantry_isolation_and_auth()
    print("test_auth OK")
