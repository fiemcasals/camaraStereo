#!/usr/bin/env python3
"""Capa de datos para el demo local de HU-01 (login, registro, recuperacion de
contrasenia, mapas). SQLite + hashlib, sin dependencias externas.

Implementa las condiciones de aprobacion de:
- RF-02 Sistema de registro a la app: registro tradicional, solicitud queda
  pendiente hasta que el administrador (mauriciocasals90@gmail.com) la aprueba.
- RF-03 Sistema de recuperacion de contrasenia: token de un solo uso con
  vencimiento, enviado "por correo" (en local se escribe a un archivo, ver
  mail_outbox.py).
"""
import sqlite3
import hashlib
import secrets
import time
import os

DB_PATH = os.environ.get("VAD_DB_PATH") or os.path.join(os.path.dirname(__file__), "app.db")
ADMIN_EMAIL = "mauriciocasals90@gmail.com"
ADMIN_USERNAME = "admin"
# En la VPS se define VAD_ADMIN_PASSWORD (ver deploy/); admin123 queda solo
# para el demo local. Se usa unicamente al crear el admin la primera vez.
ADMIN_DEFAULT_PASSWORD = os.environ.get("VAD_ADMIN_PASSWORD") or "admin123"
RESET_TOKEN_TTL_SECONDS = 30 * 60


def get_conn(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    conn = get_conn(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', -- pending | approved
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reset_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at REAL NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS maps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            graph_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(owner_id, name)
        );

        -- HU-02: ultima posicion conocida de cada vehiculo (la manda la
        -- Jetson una vez por segundo). Solo la ultima: el historial no hace
        -- falta para mostrar el auto en el mapa.
        CREATE TABLE IF NOT EXISTS vehicle_positions (
            vehicle_id TEXT PRIMARY KEY,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            heading REAL,
            status TEXT,
            updated_at REAL NOT NULL
        );
        """
    )
    conn.commit()

    admin = conn.execute("SELECT id FROM users WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
    if admin is None:
        create_user(conn, ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_DEFAULT_PASSWORD,
                    status="approved", is_admin=1)
    conn.close()


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    computed, _ = hash_password(password, salt)
    return secrets.compare_digest(computed, password_hash)


def create_user(conn, username, email, password, status="pending", is_admin=0):
    pw_hash, salt = hash_password(password)
    conn.execute(
        "INSERT INTO users (username, email, password_hash, salt, status, is_admin, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (username, email, pw_hash, salt, status, is_admin, time.time()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user_by_username(conn, username):
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user_by_email(conn, email):
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def list_pending_users(conn):
    return conn.execute("SELECT * FROM users WHERE status = 'pending'").fetchall()


def approve_user(conn, username):
    conn.execute("UPDATE users SET status = 'approved' WHERE username = ?", (username,))
    conn.commit()


def create_reset_token(conn, user_id):
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO reset_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, time.time() + RESET_TOKEN_TTL_SECONDS),
    )
    conn.commit()
    return token


def consume_reset_token(conn, token):
    row = conn.execute("SELECT * FROM reset_tokens WHERE token = ?", (token,)).fetchone()
    if row is None:
        return None
    if row["used"] or row["expires_at"] < time.time():
        return None
    conn.execute("UPDATE reset_tokens SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    return row


def set_password(conn, user_id, new_password):
    pw_hash, salt = hash_password(new_password)
    conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                 (pw_hash, salt, user_id))
    conn.commit()


def save_map(conn, owner_id, name, graph_json):
    now = time.time()
    conn.execute(
        "INSERT INTO maps (owner_id, name, graph_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(owner_id, name) DO UPDATE SET graph_json = excluded.graph_json, "
        "updated_at = excluded.updated_at",
        (owner_id, name, graph_json, now, now),
    )
    conn.commit()


def list_maps(conn, owner_id):
    return conn.execute(
        "SELECT id, name, updated_at FROM maps WHERE owner_id = ? ORDER BY updated_at DESC",
        (owner_id,),
    ).fetchall()


def get_map(conn, owner_id, map_id):
    return conn.execute(
        "SELECT * FROM maps WHERE owner_id = ? AND id = ?", (owner_id, map_id)
    ).fetchone()


def delete_map(conn, owner_id, map_id):
    conn.execute("DELETE FROM maps WHERE owner_id = ? AND id = ?", (owner_id, map_id))
    conn.commit()


def upsert_position(conn, vehicle_id, lat, lon, heading, status):
    conn.execute(
        "INSERT INTO vehicle_positions (vehicle_id, lat, lon, heading, status, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(vehicle_id) DO UPDATE SET lat = excluded.lat, "
        "lon = excluded.lon, heading = excluded.heading, status = excluded.status, "
        "updated_at = excluded.updated_at",
        (vehicle_id, lat, lon, heading, status, time.time()),
    )
    conn.commit()


def list_positions(conn):
    return conn.execute("SELECT * FROM vehicle_positions ORDER BY vehicle_id").fetchall()
