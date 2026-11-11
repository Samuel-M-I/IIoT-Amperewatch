import json
import math
import os
import random
import tempfile
import unittest

os.environ.setdefault("FLASK_SECRET_KEY", "x" * 64)

from config import Config
Config.DATABASE = os.path.join(tempfile.mkdtemp(), "test_spectrum.db")

from app import create_app, database as db
from app.auth import hashear
from app.spectrum import EspectroNoDisponible, analizar_espectro


def onda(irms=12.5, f=60.0, n=128, dt_us=1163.0, h=None, dc=0.0, ruido=0.0, jitter_us=0.0, seed=1):
    """Senoide + armónicos. h = {orden: fracción de la fundamental}. Devuelve (muestras, t_us)."""
    rnd = random.Random(seed)
    h = h or {}
    t, x = [], []
    for k in range(n):
        tk = k * dt_us + (rnd.gauss(0, jitter_us) if jitter_us else 0)
        w = 2 * math.pi * f * tk / 1e6
        v = math.sin(w) + sum(a * math.sin(o * w + 0.4 * o) for o, a in h.items())
        x.append(math.sqrt(2) * irms * v + dc + (rnd.gauss(0, ruido) if ruido else 0))
        t.append(tk)
    t0 = t[0]
    return x, [v - t0 for v in t]


class TestEspectro(unittest.TestCase):
    def test_senoide_pura_thd_casi_cero(self):
        r = analizar_espectro(*onda())
        self.assertTrue(r["disponible"])
        self.assertAlmostEqual(r["fundamental"]["freq_hz"], 60.0, delta=0.1)
        self.assertAlmostEqual(r["fundamental"]["rms_a"], 12.5, delta=0.25)
        self.assertLess(r["thd_pct"], 0.5)
        self.assertEqual(r["thd_nivel"], "bajo")

    def test_thd_y_armonicos_conocidos(self):
        r = analizar_espectro(*onda(h={3: 0.10, 5: 0.06}))
        self.assertAlmostEqual(r["thd_pct"], math.hypot(10, 6), delta=0.5)
        pct = {a["orden"]: a["pct_fundamental"] for a in r["armonicos"]}
        self.assertAlmostEqual(pct[3], 10.0, delta=0.4)
        self.assertAlmostEqual(pct[5], 6.0, delta=0.4)
        self.assertLess(pct[2], 0.5)
        self.assertEqual(pct[1], 100.0)
        self.assertEqual(r["thd_nivel"], "alto")

    def test_red_de_50_hz(self):
        r = analizar_espectro(*onda(f=50.0, h={3: 0.2}))
        self.assertAlmostEqual(r["fundamental"]["freq_hz"], 50.0, delta=0.15)
        self.assertAlmostEqual(r["thd_pct"], 20.0, delta=0.8)

    def test_robusto_a_ruido_offset_y_jitter(self):
        for seed in range(15):
            x, t = onda(f=59.8, h={3: 0.08, 5: 0.04}, ruido=0.06, dc=0.5, jitter_us=15, seed=seed)
            r = analizar_espectro(x, t)
            self.assertAlmostEqual(r["fundamental"]["freq_hz"], 59.8, delta=0.3, msg=f"seed={seed}")
            self.assertAlmostEqual(r["thd_pct"], math.hypot(8, 4), delta=1.0, msg=f"seed={seed}")

    def test_el_reloj_real_del_ads1115(self):
        """Con t_us reales la fundamental sale bien aunque el reloj no sea de 860 SPS."""
        r = analizar_espectro(*onda(dt_us=1e6 / (860 * 1.08), h={3: 0.1}))
        self.assertAlmostEqual(r["fundamental"]["freq_hz"], 60.0, delta=0.2)
        self.assertAlmostEqual(r["thd_pct"], 10.0, delta=0.6)

    def test_solo_cuenta_armonicos_bajo_nyquist(self):
        r = analizar_espectro(*onda())          # ~860 SPS, Nyquist ~430 Hz -> hasta el 6.º de 60 Hz
        self.assertEqual(r["muestreo"]["armonicos_analizados"], 6)
        self.assertLessEqual(max(a["orden"] for a in r["armonicos"]), 6)

    def test_muestreo_rapido_mide_mas_armonicos(self):
        r = analizar_espectro(*onda(n=512, dt_us=250.0, h={7: 0.05, 11: 0.03}))     # 4 kSPS
        pct = {a["orden"]: a["pct_fundamental"] for a in r["armonicos"]}
        self.assertEqual(r["muestreo"]["armonicos_analizados"], Config.ESPECTRO_MAX_ARMONICO)
        self.assertAlmostEqual(pct[7], 5.0, delta=0.4)
        self.assertAlmostEqual(r["thd_pct"], math.hypot(5, 3), delta=0.5)

    def test_json_limpio_y_tamano_acotado(self):
        r = analizar_espectro(*onda(n=2048, dt_us=250.0, h={3: 0.1}))
        json.dumps(r)                                    # solo tipos nativos
        self.assertLessEqual(len(r["espectro"]["freq_hz"]), Config.ESPECTRO_MAX_BARRAS)
        self.assertEqual(len(r["espectro"]["freq_hz"]), len(r["espectro"]["rms_a"]))
        self.assertTrue(all(type(v) is float for v in r["espectro"]["rms_a"]))
        self.assertIs(type(r["fundamental"]["freq_hz"]), float)
        # el pico del espectro comprimido conserva la fundamental
        pico = max(range(len(r["espectro"]["rms_a"])), key=r["espectro"]["rms_a"].__getitem__)
        self.assertAlmostEqual(r["espectro"]["freq_hz"][pico], 60.0, delta=2.0)

    def test_rechazos_con_motivo(self):
        casos = {
            "ventana corta (< 4 ciclos)": onda(n=16, dt_us=700),
            "sin corriente": ([0.0] * 64, [k * 1163.0 for k in range(64)]),
            "fs muy baja": onda(n=64, dt_us=5000.0, f=60.0),       # 200 SPS: ni el 2.º armónico (120 Hz) cabe bajo 0.9 x Nyquist
        }
        for nombre, (x, t) in casos.items():
            with self.assertRaises(EspectroNoDisponible, msg=nombre) as c:
                analizar_espectro(x, t)
            self.assertTrue(str(c.exception), nombre)


class TestEndpointEspectro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["SESSION_COOKIE_SECURE"] = False
        db.create_user("espectro", hashear("clave-segura-123"), "2026-01-01")

    def setUp(self):
        with db.db_cursor(commit=True) as c:
            c.execute("DELETE FROM waveform_packets")

    def _cliente(self):
        cli = self.app.test_client()
        with cli.session_transaction() as s:
            s["csrf"] = "tok"
        r = cli.post("/login", data={"username": "espectro", "password": "clave-segura-123", "csrf_token": "tok"})
        self.assertEqual(r.status_code, 302)
        return cli

    def _guardar(self, x, t, espectro, ts="2099-01-01 00:00:00.000"):
        db.insert_waveform(ts, x, t[-1] / (len(t) - 1), None, {}, espectro)

    def test_requiere_login(self):
        self.assertEqual(self.app.test_client().get("/api/espectro").status_code, 401)

    def test_sin_ondas(self):
        j = self._cliente().get("/api/espectro").get_json()
        self.assertFalse(j["disponible"])
        self.assertIn("motivo", j)
        self.assertIsNone(j["timestamp"])

    def test_devuelve_el_analisis_de_la_ultima_onda(self):
        x, t = onda(h={3: 0.1})
        self._guardar(x, t, analizar_espectro(x, t), ts=self._ahora())
        j = self._cliente().get("/api/espectro").get_json()
        self.assertTrue(j["disponible"])
        self.assertAlmostEqual(j["thd_pct"], 10.0, delta=0.6)
        self.assertAlmostEqual(j["fundamental"]["freq_hz"], 60.0, delta=0.1)
        self.assertLess(j["age_s"], 5)
        for clave in ("armonicos", "espectro", "muestreo", "thd_nivel", "sin_senal_seg", "timestamp"):
            self.assertIn(clave, j)

    def test_onda_sin_analisis_o_con_motivo(self):
        x, t = onda()
        self._guardar(x, t, None, ts=self._ahora())                  # onda anterior a esta función
        j = self._cliente().get("/api/espectro").get_json()
        self.assertFalse(j["disponible"])
        self._guardar(x, t, {"disponible": False, "motivo": "ventana corta"}, ts=self._ahora())
        j = self._cliente().get("/api/espectro").get_json()
        self.assertEqual(j["motivo"], "ventana corta")

    @staticmethod
    def _ahora():
        from app.services import timestamp_actual
        return timestamp_actual()


if __name__ == "__main__":
    unittest.main()

