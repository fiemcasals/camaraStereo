#!/usr/bin/env python3
"""Pruebas de punta a punta del demo local de HU-01: levanta el servidor real
(server.py) en un puerto de prueba con una base de datos aislada, y ejercita
con pedidos HTTP reales el flujo completo: registro -> aprobacion del admin
-> login -> guardar/listar/borrar mapas -> calcular ruta -> recuperacion de
contrasenia; mas los casos negativos (usuario sin aprobar, contrasenia
incorrecta, token de recuperacion vencido o ya usado, acceso sin sesion).

Correr con:
    python3 -m unittest web_dashboard.test_server -v
o directamente:
    python3 web_dashboard/test_server.py
"""
import unittest
import threading
import http.client
import http.server
import json
import tempfile
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import server as server_module
import db


class ApiClient:
    """Envoltorio chico sobre http.client que mantiene la cookie de sesion,
    igual que haria un navegador."""

    def __init__(self, port):
        self.port = port
        self.cookie = None

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("localhost", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        set_cookie = resp.getheader("Set-Cookie")
        if set_cookie:
            self.cookie = set_cookie.split(";", 1)[0]
        data = json.loads(raw.decode("utf-8")) if raw else {}
        conn.close()
        return resp.status, data

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body)

    def delete(self, path):
        return self.request("DELETE", path)


class ServerTestCase(unittest.TestCase):
    """Cada test levanta su propio servidor con su propia DB temporal, para
    que no se pisen entre si (evita el mismo tipo de problema de estado
    compartido que ya vimos con las fechas superpuestas en el tablero)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        server_module.SESSIONS.clear()
        self.httpd = server_module.make_server(port=0, db_path=self.db_path)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def admin_client(self):
        c = ApiClient(self.port)
        status, data = c.post("/api/login", {
            "username": db.ADMIN_USERNAME, "password": db.ADMIN_DEFAULT_PASSWORD
        })
        assert status == 200, data
        return c

    def register_and_approve(self, username="mauri", email="mauri@example.com", password="secreto1"):
        c = ApiClient(self.port)
        status, data = c.post("/api/register", {"username": username, "email": email, "password": password})
        self.assertEqual(status, 201, data)
        admin = self.admin_client()
        status, data = admin.post("/api/admin/approve", {"username": username})
        self.assertEqual(status, 200, data)
        return username, password


class TestRegistroYAprobacion(ServerTestCase):
    def test_registro_queda_pendiente_y_no_puede_loguear(self):
        c = ApiClient(self.port)
        status, data = c.post("/api/register", {
            "username": "nuevo", "email": "nuevo@example.com", "password": "secreto1"
        })
        self.assertEqual(status, 201)

        status, data = c.post("/api/login", {"username": "nuevo", "password": "secreto1"})
        self.assertEqual(status, 403)
        self.assertIn("aprobada", data["error"])

    def test_username_duplicado_es_rechazado(self):
        c = ApiClient(self.port)
        c.post("/api/register", {"username": "dup", "email": "a@example.com", "password": "secreto1"})
        status, data = c.post("/api/register", {"username": "dup", "email": "b@example.com", "password": "secreto1"})
        self.assertEqual(status, 409)

    def test_admin_aprueba_y_el_usuario_ya_puede_entrar(self):
        username, password = self.register_and_approve()
        c = ApiClient(self.port)
        status, data = c.post("/api/login", {"username": username, "password": password})
        self.assertEqual(status, 200)
        self.assertEqual(data["username"], username)

    def test_password_incorrecto_rechazado(self):
        username, _ = self.register_and_approve()
        c = ApiClient(self.port)
        status, data = c.post("/api/login", {"username": username, "password": "otra-cosa"})
        self.assertEqual(status, 401)

    def test_solo_admin_puede_ver_pendientes(self):
        self.register_and_approve()
        c = ApiClient(self.port)
        c.post("/api/register", {"username": "otro", "email": "otro@example.com", "password": "secreto1"})
        status, data = c.get("/api/admin/pending")
        self.assertEqual(status, 401)  # sin loguear


class TestRecuperacionDeContrasenia(ServerTestCase):
    def test_flujo_completo_de_recuperacion(self):
        username, _old_password = self.register_and_approve()

        c = ApiClient(self.port)
        status, data = c.post("/api/forgot-password", {"username": username})
        self.assertEqual(status, 200)

        # El "mail" queda escrito en el outbox local; de ahi se saca el token.
        # El outbox es un archivo compartido entre corridas (no aislado por
        # test como la DB), asi que se toma la ULTIMA entrada, que es la que
        # acaba de generar este test.
        with open(server_module.mail_outbox.OUTBOX_PATH, encoding="utf-8") as f:
            outbox = f.read()
        import re
        matches = re.findall(r"token=([\w\-]+)", outbox)
        self.assertTrue(matches, "no se encontro el link de recuperacion en el outbox")
        token = matches[-1]

        status, data = c.post("/api/reset-password", {"token": token, "password": "nuevaClave1"})
        self.assertEqual(status, 200)

        fresh = ApiClient(self.port)
        status, data = fresh.post("/api/login", {"username": username, "password": "nuevaClave1"})
        self.assertEqual(status, 200)

    def test_token_no_se_puede_reusar(self):
        username, _ = self.register_and_approve()
        c = ApiClient(self.port)
        c.post("/api/forgot-password", {"username": username})
        with open(server_module.mail_outbox.OUTBOX_PATH, encoding="utf-8") as f:
            outbox = f.read()
        import re
        token = re.findall(r"token=([\w\-]+)", outbox)[-1]

        status, _ = c.post("/api/reset-password", {"token": token, "password": "primeraVez1"})
        self.assertEqual(status, 200)
        status, data = c.post("/api/reset-password", {"token": token, "password": "segundaVez1"})
        self.assertEqual(status, 400)

    def test_no_revela_si_el_usuario_existe(self):
        c = ApiClient(self.port)
        status, data = c.post("/api/forgot-password", {"username": "no-existe-nadie"})
        self.assertEqual(status, 200)
        self.assertIn("Si el usuario existe", data["message"])


class TestMapas(ServerTestCase):
    def test_requiere_login_para_ver_mapas(self):
        c = ApiClient(self.port)
        status, data = c.get("/api/maps")
        self.assertEqual(status, 401)

    def test_guardar_listar_cargar_y_borrar_mapa(self):
        username, password = self.register_and_approve()
        c = ApiClient(self.port)
        c.post("/api/login", {"username": username, "password": password})

        grafo = {
            "nodes": [{"id": 1, "lat": -34.6, "lon": -58.4}, {"id": 2, "lat": -34.601, "lon": -58.401}],
            "edges": [[1, 2]],
            "destino": 2,
        }
        status, data = c.post("/api/maps", {"name": "patio", "graph": grafo})
        self.assertEqual(status, 200)

        status, data = c.get("/api/maps")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["maps"]), 1)
        self.assertEqual(data["maps"][0]["name"], "patio")
        map_id = data["maps"][0]["id"]

        status, data = c.get(f"/api/maps/{map_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data["graph"]["nodes"], grafo["nodes"])

        status, _ = c.delete(f"/api/maps/{map_id}")
        self.assertEqual(status, 200)
        status, data = c.get("/api/maps")
        self.assertEqual(len(data["maps"]), 0)

    def test_un_usuario_no_ve_los_mapas_de_otro(self):
        u1, p1 = self.register_and_approve("ana", "ana@example.com", "secreto1")
        u2, p2 = self.register_and_approve("beto", "beto@example.com", "secreto1")

        c1 = ApiClient(self.port)
        c1.post("/api/login", {"username": u1, "password": p1})
        c1.post("/api/maps", {"name": "solo-de-ana", "graph": {"nodes": [], "edges": []}})

        c2 = ApiClient(self.port)
        c2.post("/api/login", {"username": u2, "password": p2})
        status, data = c2.get("/api/maps")
        self.assertEqual(len(data["maps"]), 0)


class TestRuteo(ServerTestCase):
    """Prueba el endpoint /api/route, que envuelve el waypoint_router.py ya
    corregido (bug del Dijkstra bidireccional). Usa el mismo grafo con el que
    se detecto ese bug, para que esta prueba de regresion falle de nuevo si
    alguien reintroduce el error."""

    def setUp(self):
        super().setUp()
        self.username, self.password = self.register_and_approve()
        self.client = ApiClient(self.port)
        self.client.post("/api/login", {"username": self.username, "password": self.password})

    def test_requiere_login(self):
        c = ApiClient(self.port)
        status, data = c.post("/api/route", {"graph": {"nodes": [], "edges": []}, "origin": 1})
        self.assertEqual(status, 401)

    def test_elige_el_camino_mas_corto_no_cualquiera(self):
        # Grafo con un camino directo mas largo (via nodo 5) y una cadena mas
        # corta (1-2-3-4): el router tiene que preferir la cadena.
        grafo = {
            "nodes": [
                {"id": 1, "lat": 0.0, "lon": 0.0},
                {"id": 2, "lat": 0.0, "lon": 0.001},
                {"id": 3, "lat": 0.0, "lon": 0.002},
                {"id": 4, "lat": 0.0, "lon": 0.003},
                {"id": 5, "lat": 0.001, "lon": 0.0015},
            ],
            "edges": [[1, 2], [2, 3], [3, 4], [1, 5], [5, 4]],
            "destino": 4,
        }
        status, data = self.client.post("/api/route", {"graph": grafo, "origin": 1, "destino": 4})
        self.assertEqual(status, 200)
        self.assertEqual(data["route"]["path_ids"], [1, 2, 3, 4])

    def test_sin_camino_devuelve_null_no_error(self):
        grafo = {
            "nodes": [{"id": 1, "lat": 0.0, "lon": 0.0}, {"id": 2, "lat": 1.0, "lon": 1.0}],
            "edges": [],
            "destino": 2,
        }
        status, data = self.client.post("/api/route", {"graph": grafo, "origin": 1, "destino": 2})
        self.assertEqual(status, 200)
        self.assertIsNone(data["route"])


class TestPaginasEstaticas(ServerTestCase):
    def test_sirve_login_html(self):
        c = ApiClient(self.port)
        conn = http.client.HTTPConnection("localhost", self.port)
        conn.request("GET", "/login.html")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"Ingresar", resp.read())

    def test_ruta_desconocida_da_404(self):
        conn = http.client.HTTPConnection("localhost", self.port)
        conn.request("GET", "/no-existe.html")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)


def raw_request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("localhost", port, timeout=5)
    payload = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    h = {"Content-Type": "application/json"} if payload is not None else {}
    h.update(headers or {})
    conn.request(method, path, body=payload, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data, resp


class TestPosicionVehiculo(ServerTestCase):
    """HU-02: la Jetson manda su posicion con token; el mapa la lee con login."""

    TOKEN = "token-de-prueba-123"

    def setUp(self):
        super().setUp()
        self._tokens = dict(server_module.VEHICLE_TOKENS)
        server_module.VEHICLE_TOKENS.clear()
        server_module.VEHICLE_TOKENS["vad-01"] = self.TOKEN

    def tearDown(self):
        server_module.VEHICLE_TOKENS.clear()
        server_module.VEHICLE_TOKENS.update(self._tokens)
        super().tearDown()

    def post_pos(self, body, token=TOKEN, vehicle="vad-01"):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        status, data, _ = raw_request(self.port, "POST", f"/api/vehicles/{vehicle}/position", body, headers)
        return status, json.loads(data)

    def test_con_token_guarda_y_el_mapa_la_ve(self):
        status, _ = self.post_pos({"lat": -34.6037, "lon": -58.3816, "heading": 90.0, "status": "navegando"})
        self.assertEqual(status, 200)
        status, data = self.admin_client().get("/api/vehicles")
        self.assertEqual(status, 200)
        v = data["vehicles"][0]
        self.assertEqual((v["id"], v["lat"], v["lon"], v["heading"], v["status"]), ("vad-01", -34.6037, -58.3816, 90.0, "navegando"))
        self.assertFalse(v["stale"])
        self.assertLess(v["age_s"], 5)

    def test_la_ultima_posicion_reemplaza_a_la_anterior(self):
        self.post_pos({"lat": -34.0, "lon": -58.0})
        self.post_pos({"lat": -34.1, "lon": -58.1})
        _, data = self.admin_client().get("/api/vehicles")
        self.assertEqual(len(data["vehicles"]), 1)
        self.assertEqual(data["vehicles"][0]["lat"], -34.1)

    def test_sin_token_token_invalido_u_otro_vehiculo_da_401(self):
        self.assertEqual(self.post_pos({"lat": 1, "lon": 1}, token=None)[0], 401)
        self.assertEqual(self.post_pos({"lat": 1, "lon": 1}, token="otro")[0], 401)
        self.assertEqual(self.post_pos({"lat": 1, "lon": 1}, vehicle="vad-99")[0], 401)

    def test_coordenadas_invalidas_dan_400(self):
        self.assertEqual(self.post_pos({"lat": 95, "lon": 1})[0], 400)
        self.assertEqual(self.post_pos({"lat": "abc", "lon": 1})[0], 400)
        self.assertEqual(self.post_pos({"lon": 1})[0], 400)

    def test_ver_vehiculos_exige_login(self):
        status, _ = ApiClient(self.port).get("/api/vehicles")
        self.assertEqual(status, 401)

    def test_sin_senal_si_la_posicion_es_vieja(self):
        self.post_pos({"lat": -34.0, "lon": -58.0})
        conn = db.get_conn(self.db_path)
        conn.execute("UPDATE vehicle_positions SET updated_at = updated_at - 30")
        conn.commit(); conn.close()
        _, data = self.admin_client().get("/api/vehicles")
        self.assertTrue(data["vehicles"][0]["stale"])


class FakePresupuesto(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = f"presupuesto GET {self.path}".encode()
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); got = self.rfile.read(n)
        body = b"guardado:" + got
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


class TestPresupuestoYSeguridad(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.up = http.server.HTTPServer(("localhost", 0), FakePresupuesto)
        threading.Thread(target=self.up.serve_forever, daemon=True).start()
        self._old = server_module.PRESUPUESTO_UPSTREAM
        server_module.PRESUPUESTO_UPSTREAM = f"http://localhost:{self.up.server_address[1]}"

    def tearDown(self):
        server_module.PRESUPUESTO_UPSTREAM = self._old
        self.up.shutdown(); self.up.server_close()
        super().tearDown()

    def test_presupuesto_se_reenvia_sin_el_prefijo(self):
        status, data, _ = raw_request(self.port, "GET", "/presupuesto/presupuesto.html")
        self.assertEqual((status, data), (200, b"presupuesto GET /presupuesto.html"))
        status, data, _ = raw_request(self.port, "GET", "/presupuesto/")
        self.assertEqual(data, b"presupuesto GET /")

    def test_presupuesto_sin_barra_redirige(self):
        status, _, resp = raw_request(self.port, "GET", "/presupuesto")
        self.assertEqual((status, resp.getheader("Location")), (301, "/presupuesto/"))

    def test_api_budget_se_reenvia_con_el_cuerpo(self):
        status, data, _ = raw_request(self.port, "POST", "/api/budget", {"total": 10})
        self.assertEqual((status, data), (200, b'guardado:{"total": 10}'))

    def test_no_se_sirven_db_log_ni_codigo(self):
        for path in ("/app.db", "/mail_outbox.log", "/server.py", "/db.py"):
            status, _, _ = raw_request(self.port, "GET", path)
            self.assertEqual(status, 404, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
