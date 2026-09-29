#!/usr/bin/env python3
"""Servidor local para probar de punta a punta los Requerimientos de HU-01
(generacion de carga de mapas y puntos de ruteo): login, registro con
aprobacion del administrador, recuperacion de contrasenia, guardado/borrado
de mapas, y calculo de ruta reusando waypoint_router.py (ya con el fix del
bug de Dijkstra bidireccional).

Solo libreria estandar de Python (http.server + sqlite3), para poder
correrlo sin instalar nada:

    python3 web_dashboard/server.py [puerto]   # default 8080

Despues abrir http://localhost:8080/login.html
Usuario admin ya creado: admin / admin123 (ver db.ADMIN_DEFAULT_PASSWORD).
"""
import sys
import os
import json
import math
import secrets
import time
import http.server
import http.cookies
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "zed_costmap_nav", "scripts"))

import db
import mail_outbox
import waypoint_router

STATIC_DIR = os.path.dirname(__file__)
SESSION_COOKIE = "vad_session"

# HU-02: tokens de los vehiculos, "vad-01:token1,vad-02:token2". Sin esto el
# endpoint de posicion rechaza todo (401).
VEHICLE_TOKENS = dict(
    item.split(":", 1) for item in os.environ.get("VAD_VEHICLE_TOKENS", "").split(",") if ":" in item
)
# Presupuesto (app Node aparte en la VPS): /presupuesto/* y /api/budget se
# reenvian ahi, asi comparte el dominio sin tocar esa app. Vacio = no se usa.
PRESUPUESTO_UPSTREAM = os.environ.get("VAD_PRESUPUESTO_UPSTREAM", "").rstrip("/")
# Pagina a la que lleva "/". En la VPS no corre ROS, asi que el HUD de
# index.html no sirve: se usa VAD_HOME=/map_editor.html.
HOME_PAGE = os.environ.get("VAD_HOME", "/index.html")
# Sin senal: si la ultima posicion tiene mas de esto, el mapa lo avisa.
POSITION_STALE_S = 10

# token de sesion -> username. En memoria: alcanza para un demo local, se
# pierde al reiniciar el servidor (igual que las sesiones de cualquier app
# que no las persista aparte).
SESSIONS = {}


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def get_session_user(handler):
    cookie_header = handler.headers.get("Cookie")
    if not cookie_header:
        return None
    cookies = http.cookies.SimpleCookie(cookie_header)
    if SESSION_COOKIE not in cookies:
        return None
    token = cookies[SESSION_COOKIE].value
    return SESSIONS.get(token)


def set_session_cookie(handler, token):
    # Detras del proxy con HTTPS la cookie viaja solo cifrada.
    secure = "; Secure; SameSite=Lax" if handler.headers.get("X-Forwarded-Proto") == "https" else ""
    handler.send_header("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; HttpOnly{secure}")


def clear_session_cookie(handler):
    handler.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0")


class Handler(http.server.BaseHTTPRequestHandler):
    db_path = None  # override en los tests para usar una DB aislada

    def log_message(self, fmt, *args):
        pass  # silenciar el log de acceso por default; usar -v para verlo

    # ---------- helpers ----------

    def conn(self):
        return db.get_conn(self.db_path)

    def require_login(self):
        username = get_session_user(self)
        if username is None:
            json_response(self, 401, {"error": "no autenticado"})
            return None
        conn = self.conn()
        user = db.get_user_by_username(conn, username)
        conn.close()
        if user is None or user["status"] != "approved":
            json_response(self, 401, {"error": "no autenticado"})
            return None
        return user

    # ---------- GET ----------

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if self.is_presupuesto_path(path):
            return self.proxy_presupuesto(parsed)

        if path == "/api/vehicles":
            user = self.require_login()
            if user is None:
                return
            conn = self.conn()
            rows = db.list_positions(conn)
            conn.close()
            now = time.time()
            return json_response(self, 200, {"vehicles": [{
                "id": r["vehicle_id"], "lat": r["lat"], "lon": r["lon"], "heading": r["heading"],
                "status": r["status"], "age_s": round(now - r["updated_at"], 1),
                "stale": now - r["updated_at"] > POSITION_STALE_S,
            } for r in rows]})

        if path == "/api/me":
            username = get_session_user(self)
            if username is None:
                return json_response(self, 200, {"authenticated": False})
            conn = self.conn()
            user = db.get_user_by_username(conn, username)
            conn.close()
            if user is None:
                return json_response(self, 200, {"authenticated": False})
            return json_response(self, 200, {
                "authenticated": True,
                "username": user["username"],
                "is_admin": bool(user["is_admin"]),
            })

        if path == "/api/maps":
            user = self.require_login()
            if user is None:
                return
            conn = self.conn()
            rows = db.list_maps(conn, user["id"])
            conn.close()
            return json_response(self, 200, {
                "maps": [{"id": r["id"], "name": r["name"], "updated_at": r["updated_at"]} for r in rows]
            })

        if path.startswith("/api/maps/"):
            user = self.require_login()
            if user is None:
                return
            map_id = path.rsplit("/", 1)[-1]
            conn = self.conn()
            row = db.get_map(conn, user["id"], map_id)
            conn.close()
            if row is None:
                return json_response(self, 404, {"error": "mapa no encontrado"})
            return json_response(self, 200, {
                "id": row["id"], "name": row["name"], "graph": json.loads(row["graph_json"])
            })

        if path == "/api/admin/pending":
            user = self.require_login()
            if user is None:
                return
            if not user["is_admin"]:
                return json_response(self, 403, {"error": "solo el administrador"})
            conn = self.conn()
            rows = db.list_pending_users(conn)
            conn.close()
            return json_response(self, 200, {
                "pending": [{"username": r["username"], "email": r["email"]} for r in rows]
            })

        return self.serve_static(path)

    # ---------- POST ----------

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.is_presupuesto_path(path):
            return self.proxy_presupuesto(parsed)
        try:
            body = read_json_body(self)
        except (ValueError, json.JSONDecodeError):
            return json_response(self, 400, {"error": "JSON invalido"})

        if path == "/api/register":
            return self.handle_register(body)
        if path == "/api/login":
            return self.handle_login(body)
        if path == "/api/logout":
            return self.handle_logout()
        if path == "/api/forgot-password":
            return self.handle_forgot_password(body)
        if path == "/api/reset-password":
            return self.handle_reset_password(body)
        if path == "/api/maps":
            return self.handle_save_map(body)
        if path == "/api/route":
            return self.handle_route(body)
        if path == "/api/admin/approve":
            return self.handle_admin_approve(body)
        if path.startswith("/api/vehicles/") and path.endswith("/position"):
            return self.handle_vehicle_position(path.split("/")[3], body)

        return json_response(self, 404, {"error": "no encontrado"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/maps/"):
            user = self.require_login()
            if user is None:
                return
            map_id = path.rsplit("/", 1)[-1]
            conn = self.conn()
            db.delete_map(conn, user["id"], map_id)
            conn.close()
            return json_response(self, 200, {"ok": True})
        return json_response(self, 404, {"error": "no encontrado"})

    # ---------- handlers ----------

    def handle_register(self, body):
        username = (body.get("username") or "").strip()
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
        if not username or not email or not password:
            return json_response(self, 400, {"error": "username, email y password son requeridos"})
        if len(password) < 6:
            return json_response(self, 400, {"error": "la contrasenia debe tener al menos 6 caracteres"})

        conn = self.conn()
        if db.get_user_by_username(conn, username) is not None:
            conn.close()
            return json_response(self, 409, {"error": "ese username ya existe"})
        if db.get_user_by_email(conn, email) is not None:
            conn.close()
            return json_response(self, 409, {"error": "ese email ya esta registrado"})

        db.create_user(conn, username, email, password, status="pending")
        conn.close()

        mail_outbox.send(
            db.ADMIN_EMAIL,
            "Nueva solicitud de registro en VAD",
            f"El usuario '{username}' ({email}) pidio acceso a la aplicacion. "
            f"Entra como administrador y aprobalo desde /admin.html.",
        )
        return json_response(self, 201, {
            "ok": True,
            "message": "Solicitud enviada. Un administrador tiene que aprobarla antes de poder ingresar."
        })

    def handle_login(self, body):
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        conn = self.conn()
        user = db.get_user_by_username(conn, username)
        conn.close()
        if user is None or not db.verify_password(password, user["password_hash"], user["salt"]):
            return json_response(self, 401, {"error": "usuario o contrasenia incorrectos"})
        if user["status"] != "approved":
            return json_response(self, 403, {"error": "tu cuenta todavia no fue aprobada por el administrador"})

        token = secrets.token_urlsafe(32)
        SESSIONS[token] = user["username"]
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        set_session_cookie(self, token)
        payload = json.dumps({"ok": True, "username": user["username"], "is_admin": bool(user["is_admin"])}).encode()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_logout(self):
        cookie_header = self.headers.get("Cookie")
        if cookie_header:
            cookies = http.cookies.SimpleCookie(cookie_header)
            if SESSION_COOKIE in cookies:
                SESSIONS.pop(cookies[SESSION_COOKIE].value, None)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        clear_session_cookie(self)
        payload = json.dumps({"ok": True}).encode()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_forgot_password(self, body):
        identifier = (body.get("username") or body.get("email") or "").strip()
        conn = self.conn()
        user = db.get_user_by_username(conn, identifier) or db.get_user_by_email(conn, identifier.lower())
        # Nunca revelar si el usuario existe o no: la respuesta es la misma
        # en ambos casos, para no filtrar qué cuentas están registradas.
        if user is not None:
            token = db.create_reset_token(conn, user["id"])
            reset_link = f"/reset_password.html?token={token}"
            mail_outbox.send(
                user["email"],
                "Recuperacion de contrasenia - VAD",
                f"Para elegir una contrasenia nueva entra a: {reset_link}\n"
                f"El link vence en {db.RESET_TOKEN_TTL_SECONDS // 60} minutos.",
            )
        conn.close()
        return json_response(self, 200, {
            "ok": True,
            "message": "Si el usuario existe, se mando un mail con el link de recuperacion."
        })

    def handle_reset_password(self, body):
        token = body.get("token") or ""
        new_password = body.get("password") or ""
        if len(new_password) < 6:
            return json_response(self, 400, {"error": "la contrasenia debe tener al menos 6 caracteres"})
        conn = self.conn()
        row = db.consume_reset_token(conn, token)
        if row is None:
            conn.close()
            return json_response(self, 400, {"error": "el link es invalido o ya vencio"})
        db.set_password(conn, row["user_id"], new_password)
        conn.close()
        return json_response(self, 200, {"ok": True, "message": "Contrasenia actualizada."})

    def handle_admin_approve(self, body):
        user = self.require_login()
        if user is None:
            return
        if not user["is_admin"]:
            return json_response(self, 403, {"error": "solo el administrador"})
        username = body.get("username") or ""
        conn = self.conn()
        target = db.get_user_by_username(conn, username)
        if target is None:
            conn.close()
            return json_response(self, 404, {"error": "usuario no encontrado"})
        db.approve_user(conn, username)
        conn.close()
        return json_response(self, 200, {"ok": True})

    def handle_save_map(self, body):
        user = self.require_login()
        if user is None:
            return
        name = (body.get("name") or "").strip()
        graph = body.get("graph")
        if not name or not isinstance(graph, dict) or "nodes" not in graph:
            return json_response(self, 400, {"error": "faltan 'name' o 'graph' (con 'nodes')"})
        conn = self.conn()
        db.save_map(conn, user["id"], name, json.dumps(graph, ensure_ascii=False))
        conn.close()
        return json_response(self, 200, {"ok": True})

    def handle_route(self, body):
        user = self.require_login()
        if user is None:
            return
        graph = body.get("graph")
        origin = body.get("origin")
        destino = body.get("destino")
        if not isinstance(graph, dict) or origin is None:
            return json_response(self, 400, {"error": "faltan 'graph' u 'origin'"})
        try:
            origin = int(origin)
            destino = int(destino) if destino is not None else None
            result = waypoint_router.compute_route(graph, origin, destino)
        except (ValueError, KeyError) as e:
            return json_response(self, 400, {"error": str(e)})
        if result is None:
            return json_response(self, 200, {"ok": True, "route": None,
                                              "message": "sin camino posible entre esos dos puntos"})
        return json_response(self, 200, {"ok": True, "route": result})

    def handle_vehicle_position(self, vehicle_id, body):
        """HU-02: la Jetson manda su posicion con 'Authorization: Bearer <token>'."""
        expected = VEHICLE_TOKENS.get(vehicle_id)
        auth = self.headers.get("Authorization", "")
        given = auth[7:] if auth.startswith("Bearer ") else ""
        if not expected or not secrets.compare_digest(given, expected):
            return json_response(self, 401, {"error": "token de vehiculo invalido"})
        try:
            lat, lon = float(body["lat"]), float(body["lon"])
            heading = float(body["heading"]) if body.get("heading") is not None else None
        except (KeyError, TypeError, ValueError):
            return json_response(self, 400, {"error": "faltan 'lat' y 'lon' numericos"})
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return json_response(self, 400, {"error": "lat/lon fuera de rango"})
        if heading is not None and not math.isfinite(heading):
            heading = None
        status = str(body.get("status") or "")[:40]
        conn = self.conn()
        db.upsert_position(conn, vehicle_id, lat, lon, heading, status)
        conn.close()
        return json_response(self, 200, {"ok": True})

    # ---------- presupuesto (app aparte) ----------

    def is_presupuesto_path(self, path):
        return bool(PRESUPUESTO_UPSTREAM) and (
            path == "/presupuesto" or path.startswith("/presupuesto/") or path == "/api/budget")

    def proxy_presupuesto(self, parsed):
        if parsed.path == "/presupuesto":
            self.send_response(301)
            self.send_header("Location", "/presupuesto/")
            self.end_headers()
            return
        upstream_path = parsed.path[len("/presupuesto"):] if parsed.path.startswith("/presupuesto/") else parsed.path
        url = PRESUPUESTO_UPSTREAM + upstream_path + (f"?{parsed.query}" if parsed.query else "")
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length) if length else None
        headers = {"Content-Type": self.headers.get("Content-Type", "application/octet-stream")} if data else {}
        req = urllib.request.Request(url, data=data, method=self.command, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status, body, ctype = resp.status, resp.read(), resp.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            status, body, ctype = e.code, e.read(), e.headers.get("Content-Type")
        except (urllib.error.URLError, OSError):
            return json_response(self, 502, {"error": "el presupuesto no responde"})
        self.send_response(status)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- estaticos ----------

    def serve_static(self, path):
        if path == "/":
            if HOME_PAGE != "/index.html":
                self.send_response(302)
                self.send_header("Location", HOME_PAGE)
                self.end_headers()
                return
            path = "/index.html"
        safe_path = os.path.normpath(path).lstrip("/")
        full_path = os.path.join(STATIC_DIR, safe_path)
        if not os.path.abspath(full_path).startswith(os.path.abspath(STATIC_DIR)):
            return json_response(self, 403, {"error": "prohibido"})
        content_types = {
            ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript",
            ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
        }
        ext = os.path.splitext(full_path)[1]
        # Solo archivos web: nunca app.db, mail_outbox.log (links de reseteo)
        # ni el codigo .py, que viven en la misma carpeta.
        if ext not in content_types or not os.path.isfile(full_path):
            return json_response(self, 404, {"error": "no encontrado"})
        content_type = content_types[ext]
        with open(full_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_server(port=8080, db_path=None):
    db.init_db(db_path)
    HandlerWithDb = type("HandlerWithDb", (Handler,), {"db_path": db_path})
    return http.server.ThreadingHTTPServer(("0.0.0.0", port), HandlerWithDb)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("VAD_PORT", 8080))
    server = make_server(port)
    print(f"Servidor local del demo VAD en http://localhost:{port}/login.html")
    if not os.environ.get("VAD_ADMIN_PASSWORD"):
        print(f"Admin ya creado: usuario '{db.ADMIN_USERNAME}' / contrasenia '{db.ADMIN_DEFAULT_PASSWORD}'")
    print(f"Los 'mails' simulados quedan en {mail_outbox.OUTBOX_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
