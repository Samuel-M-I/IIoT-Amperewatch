import math
import os
import random
import unittest

os.environ.setdefault("FLASK_SECRET_KEY", "x" * 64)
from app.analysis import PaqueteInvalido, analizar_onda, parsear_paquete_onda


def senoide(irms=12.0, f=60.0, n=128, dt_us=1163.0, dc=0.0, ruido=0.0, fase=0.0, armonicos=False, jitter_us=0.0, seed=1):
    rnd = random.Random(seed)
    t, x = [], []
    for k in range(n):
        tk = k * dt_us + (rnd.gauss(0, jitter_us) if jitter_us else 0)
        w = 2 * math.pi * f * tk / 1e6 + fase
        v = math.sin(w)
        if armonicos:
            v = (v + 0.06 * math.sin(3 * w + 0.7) + 0.03 * math.sin(5 * w + 1.3)) / math.sqrt(1 + 0.06**2 + 0.03**2)
        x.append(math.sqrt(2) * irms * v + dc + (rnd.gauss(0, ruido) if ruido else 0))
        t.append(tk)
    t0 = t[0]
    return x, [v - t0 for v in t]


class TestMediciones(unittest.TestCase):
    def test_senoide_limpia(self):
        x, t = senoide()
        m = analizar_onda(x, t)
        self.assertAlmostEqual(m["freq"], 60.0, delta=0.1)
        self.assertAlmostEqual(m["irms"], 12.0, delta=0.12)       # 1 %
        self.assertAlmostEqual(m["ip"], 12.0 * math.sqrt(2), delta=0.25)
        self.assertAlmostEqual(m["idc"], 0.0, delta=0.3)
        self.assertAlmostEqual(m["crest"], math.sqrt(2), delta=0.05)

    def test_precision_con_ruido_armonicos_y_jitter(self):
        for seed in range(20):
            for fase in (0.0, 1.1, 2.7, 4.9):
                x, t = senoide(irms=12.5, f=59.8, ruido=0.06, armonicos=True, jitter_us=15, dc=0.03, fase=fase, seed=seed)
                m = analizar_onda(x, t)
                self.assertAlmostEqual(m["freq"], 59.8, delta=0.4, msg=f"seed={seed} fase={fase}")
                self.assertAlmostEqual(m["irms"], 12.5, delta=0.30, msg=f"seed={seed} fase={fase}")

    def test_rango_de_corrientes(self):
        for irms in (0.2, 1, 5, 12, 38, 120):
            x, t = senoide(irms=irms)
            m = analizar_onda(x, t)
            self.assertAlmostEqual(m["irms"] / irms, 1.0, delta=0.03, msg=f"irms={irms}")
            self.assertAlmostEqual(m["freq"], 60.0, delta=0.3)

    def test_offset_continuo_no_rompe_frecuencia(self):
        x, t = senoide(irms=8, dc=2.5)
        m = analizar_onda(x, t)
        self.assertAlmostEqual(m["freq"], 60.0, delta=0.2)
        self.assertAlmostEqual(m["idc"], 2.5, delta=0.1)

    def test_offset_no_se_contamina_con_ciclos_partidos(self):
        """Regresión: antes el offset se medía en toda la ventana y un ciclo partido
        lo falseaba (0.6 A de 'offset' con una señal de 12 A y offset real de 0.03 A)."""
        for fase in (0.0, 0.8, 1.6, 2.4, 3.2, 4.0, 4.8, 5.6):
            x, t = senoide(irms=13.0, f=60.1, dc=0.03, fase=fase, ruido=0.06, armonicos=True, jitter_us=15)
            self.assertAlmostEqual(analizar_onda(x, t)["idc"], 0.03, delta=0.12, msg=f"fase={fase}")

    def test_extremos(self):
        x, t = senoide(irms=10)
        m = analizar_onda(x, t)
        self.assertEqual(m["imax"], round(max(x), 3))
        self.assertEqual(m["imin"], round(min(x), 3))
        self.assertAlmostEqual(m["ipp"], max(x) - min(x), places=2)

    def test_ventana_menor_a_un_ciclo_no_inventa_frecuencia(self):
        x, t = senoide(n=16, dt_us=700)          # 11 ms < 16.7 ms
        m = analizar_onda(x, t)
        self.assertIsNone(m["freq"])
        self.assertGreater(m["irms"], 0)

    def test_linea_plana_sin_senal(self):
        m = analizar_onda([0.0] * 64, [k * 1163.0 for k in range(64)])
        self.assertIsNone(m["freq"])
        self.assertEqual(m["irms"], 0.0)
        self.assertIsNone(m["crest"])

    def test_solo_ruido_no_da_frecuencia_falsa_estable(self):
        rnd = random.Random(3)
        x = [rnd.gauss(0, 0.01) for _ in range(128)]       # ip < umbral de amplitud
        self.assertIsNone(analizar_onda(x, [k * 1163.0 for k in range(128)])["freq"])

    def test_el_reloj_del_ads1115_importa(self):
        """Reloj real +8 % vs 860 SPS nominales: con t_us la frecuencia es correcta;
        suponiendo 860 SPS el error sería de varios Hz."""
        dt_real = 1e6 / (860 * 1.08)
        x, t = senoide(dt_us=dt_real)
        con_tiempos_reales = analizar_onda(x, t)["freq"]
        suponiendo_nominal = analizar_onda(x, [k * 1e6 / 860 for k in range(len(x))])["freq"]
        self.assertAlmostEqual(con_tiempos_reales, 60.0, delta=0.2)
        self.assertGreater(abs(suponiendo_nominal - 60.0), 3.0)


class TestValidacion(unittest.TestCase):
    def ok(self, **extra):
        d = {"samples": [0.1 * k for k in range(32)], "dt_us": 1163}
        d.update(extra)
        return d

    def test_formatos_validos(self):
        self.assertAlmostEqual(parsear_paquete_onda(self.ok()).dt_us, 1163)
        d = self.ok(); d.pop("dt_us"); d["fs"] = 860
        self.assertAlmostEqual(parsear_paquete_onda(d).dt_us, 1e6 / 860)
        d = self.ok(); d.pop("dt_us"); d["t_us"] = [5000 + k * 1100 for k in range(32)]   # tiempos absolutos
        o = parsear_paquete_onda(d)
        self.assertEqual(o.t_us[0], 0)
        self.assertAlmostEqual(o.dt_us, 1100)
        self.assertIsNotNone(o.t_irregular)

    def rechaza(self, d, texto=""):
        with self.assertRaises(PaqueteInvalido) as c:
            parsear_paquete_onda(d)
        self.assertIn(texto, str(c.exception))

    def test_rechazos(self):
        self.rechaza([1, 2, 3])
        self.rechaza({"dt_us": 1000}, "samples")
        self.rechaza(self.ok(samples="hola"), "lista")
        self.rechaza(self.ok(samples=[1.0] * 4), "fuera de rango")
        self.rechaza(self.ok(samples=[1.0] * 5000), "fuera de rango")
        self.rechaza(self.ok(samples=[float("nan")] * 32), "no finito")
        self.rechaza(self.ok(samples=[float("inf")] * 32), "no finito")
        self.rechaza(self.ok(samples=["1"] * 32), "no numérico")
        self.rechaza(self.ok(samples=[True] * 32), "no numérico")
        self.rechaza(self.ok(samples=[5000.0] * 32), "|I|")
        self.rechaza({"samples": [1.0] * 32}, "tiempo")
        self.rechaza(self.ok(dt_us=0.5), "periodo")
        self.rechaza(self.ok(dt_us=5e6), "periodo")
        self.rechaza(self.ok(dt_us=-5), "periodo")
        d = self.ok(); d.pop("dt_us"); d["fs"] = 0; self.rechaza(d, "positiva")
        d = self.ok(); d.pop("dt_us"); d["t_us"] = list(range(10)); self.rechaza(d, "mismo largo")
        d = self.ok(); d.pop("dt_us"); d["t_us"] = [0, 5] + [4] * 30; self.rechaza(d, "creciente")
        d = self.ok(); d.pop("dt_us"); d["t_us"] = [0.0] * 32; self.rechaza(d, "creciente")


if __name__ == "__main__":
    unittest.main()
