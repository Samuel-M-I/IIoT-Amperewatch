import os
import tempfile
import unittest

os.environ.setdefault("FLASK_SECRET_KEY", "x" * 64)
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["SESSION_COOKIE_SECURE"] = "false"

from config import Config
Config.DATABASE = os.environ["DATABASE_PATH"]

from app import create_app, database as db
from app.auth import hashear
from app.services import AjusteInvalido, clasificar_estado, guardar_umbral, obtener_umbral


class TestUmbral(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        db.create_user("admin", hashear("clave-segura-123"), "2026-01-01")

    def setUp(self):
        with db.db_cursor(commit=True) as c:
            c.execute("DELETE FROM settings")

    def test_por_defecto_usa_config(self):
        self.assertEqual(obtener_umbral(), Config.UMBRAL_SOBRECARGA)

    def test_guardar_cambia_la_clasificacion(self):
        self.assertEqual(clasificar_estado(12), "NORMAL")
        guardar_umbral(10)
        self.assertEqual(obtener_umbral(), 10.0)
        self.assertEqual(clasificar_estado(12), "ALERTA_SOBRECARGA")
        self.assertEqual(clasificar_estado(9.99), "NORMAL")

    def test_valores_invalidos(self):
        for malo in (0, -5, 0.01, 5000, float("nan"), float("inf"), "12", None, True):
            with self.assertRaises(AjusteInvalido, msg=repr(malo)):
                guardar_umbral(malo)
        self.assertEqual(obtener_umbral(), Config.UMBRAL_SOBRECARGA)

    def _cliente_logueado(self):
        cli = self.app.test_client()
        # Login real (se siembra un token CSRF en la sesión, como hace la página de login)
        with cli.session_transaction() as s:
            s["csrf"] = "tok-prueba"
        r = cli.post("/login", data={"username": "admin", "password": "clave-segura-123",
                                     "csrf_token": "tok-prueba"})
        self.assertEqual(r.status_code, 302)
        with cli.session_transaction() as s:
            return cli, s["csrf"]

    def test_endpoint_requiere_login(self):
        r = self.app.test_client().post("/api/umbral", json={"umbral": 10})
        self.assertEqual(r.status_code, 401)

    def test_endpoint_requiere_csrf(self):
        cli, token = self._cliente_logueado()
        self.assertEqual(cli.post("/api/umbral", json={"umbral": 10}).status_code, 403)
        self.assertEqual(cli.post("/api/umbral", json={"umbral": 10},
                                  headers={"X-CSRF-Token": "falso"}).status_code, 403)
        self.assertEqual(obtener_umbral(), Config.UMBRAL_SOBRECARGA)

    def test_endpoint_guarda_y_api_data_lo_refleja(self):
        cli, token = self._cliente_logueado()
        h = {"X-CSRF-Token": token}
        r = cli.post("/api/umbral", json={"umbral": 11.5}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["umbral_sobrecarga"], 11.5)
        self.assertEqual(cli.get("/api/data").get_json()["umbral_sobrecarga"], 11.5)
        self.assertIn(b'value="11.5"', cli.get("/").data)

    def test_endpoint_rechaza_basura(self):
        cli, token = self._cliente_logueado()
        h = {"X-CSRF-Token": token}
        self.assertEqual(cli.post("/api/umbral", json={"umbral": -3}, headers=h).status_code, 400)
        self.assertEqual(cli.post("/api/umbral", json={"umbral": "abc"}, headers=h).status_code, 400)
        self.assertEqual(cli.post("/api/umbral", json={}, headers=h).status_code, 400)
        self.assertEqual(cli.post("/api/umbral", data="no json", headers=h).status_code, 400)


if __name__ == "__main__":
    unittest.main()
