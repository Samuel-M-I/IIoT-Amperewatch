"""Análisis espectral de la corriente: FFT, frecuencia fundamental, armónicos y THD.

Usa numpy. (analysis.py sigue siendo Python puro: aquí la FFT lo justifica.)

Procedimiento:
  1. Si los instantes de muestreo no son uniformes (jitter de micros() en la ESP32), se remuestrea la
     ventana con interpolación lineal a una rejilla uniforme. La FFT exige muestreo uniforme.
  2. Se quita la componente continua y se aplica una ventana de Hann (reduce la fuga espectral
     entre la fundamental y sus armónicos).
  3. FFT con relleno de ceros (x8): no añade información, pero permite leer con precisión la
     posición y la altura de cada pico (interpolación parabólica).
  4. La fundamental es el pico más alto dentro de ESPECTRO_FUND_MIN_HZ..ESPECTRO_FUND_MAX_HZ.
  5. Cada armónico h se mide como el máximo del espectro alrededor de h x f1.
  6. THD = raíz(suma de A_h^2, h = 2..H) / A_1 x 100   (THD-F: referido a la fundamental).

Límites físicos (se devuelven en "muestreo" para que sean visibles):
  * Solo se miden armónicos por debajo de 0.9 x Nyquist. A ~860 SPS (Nyquist 430 Hz) en una red de
    60 Hz son hasta el 6.º armónico: el THD ignora lo que quede por encima.
  * La ventana debe contener al menos ESPECTRO_MIN_CICLOS ciclos de la fundamental.
"""
import math

import numpy as np

from config import Config


class EspectroNoDisponible(ValueError):
    """La ventana no permite un análisis espectral fiable (el mensaje explica por qué)."""


def _refinar_pico(amp, k):
    """Interpolación parabólica (sobre log-amplitud) alrededor del máximo local `k`.
    Devuelve (índice fraccionario del pico, amplitud del pico)."""
    if k <= 0 or k >= len(amp) - 1:
        return float(k), float(amp[k])
    a, b, c = np.log(amp[k - 1:k + 2] + 1e-12)
    den = a - 2.0 * b + c
    if den >= 0:                       # no es un máximo (zona plana): sin refinar
        return float(k), float(amp[k])
    p = float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
    return k + p, float(np.exp(b - 0.25 * (a - c) * p))


def _comprimir_maximos(freqs, amps, max_puntos):
    """Reduce el espectro a `max_puntos` barras quedándose con el máximo de cada grupo (no pierde picos)."""
    m = len(freqs)
    if m <= max_puntos:
        return freqs, amps
    g = int(math.ceil(m / max_puntos))
    grupos = int(math.ceil(m / g))
    relleno = np.zeros(grupos * g - m)
    pos = np.concatenate([amps, relleno]).reshape(grupos, g).argmax(axis=1) + np.arange(grupos) * g
    pos = np.minimum(pos, m - 1)
    return freqs[pos], amps[pos]


def _nivel_thd(thd):
    if thd >= Config.ESPECTRO_THD_ALTO_PCT:
        return "alto"
    if thd >= Config.ESPECTRO_THD_MODERADO_PCT:
        return "moderado"
    return "bajo"


def analizar_espectro(muestras, t_us):
    """Espectro de una ventana de corriente.

    muestras : corrientes en A | t_us : instantes (µs) relativos a la primera muestra (estrictamente crecientes).
    Devuelve un dict listo para JSON (solo tipos nativos de Python).
    Lanza EspectroNoDisponible si la ventana no sirve para este análisis.
    """
    x = np.asarray(muestras, dtype=float)
    t = np.asarray(t_us, dtype=float)
    n = len(x)
    if n < 8 or len(t) != n:
        raise EspectroNoDisponible("ventana demasiado corta")

    dt_us = t[-1] / (n - 1)
    fs = 1e6 / dt_us
    nyquist = fs / 2.0

    # 1) rejilla uniforme (solo si hay jitter apreciable)
    uniforme = np.arange(n) * dt_us
    if np.max(np.abs(t - uniforme)) > 0.002 * dt_us:
        x = np.interp(uniforme, t, x)

    # 2) ventana de Hann periódica; se resta su media ponderada para que no quede componente continua
    w = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)
    xw = (x - np.sum(w * x) / np.sum(w)) * w

    # 3) FFT con relleno de ceros; 2|X|/sum(w) = amplitud pico de cada senoide
    nfft = 1 << int(math.ceil(math.log2(n * Config.ESPECTRO_ZERO_PAD)))
    amp = 2.0 * np.abs(np.fft.rfft(xw, nfft)) / np.sum(w)
    freqs = np.fft.rfftfreq(nfft, d=dt_us * 1e-6)
    df_ventana = fs / n                      # resolución real (la del tiempo de captura)

    # 4) fundamental
    banda = np.where((freqs >= Config.ESPECTRO_FUND_MIN_HZ) &
                     (freqs <= min(Config.ESPECTRO_FUND_MAX_HZ, nyquist)))[0]
    if len(banda) < 3:
        raise EspectroNoDisponible("frecuencia de muestreo insuficiente para buscar la fundamental")
    k = int(banda[np.argmax(amp[banda])])
    if amp[k] < Config.FREQ_MIN_AMP_A:
        raise EspectroNoDisponible("señal demasiado débil (sin corriente)")
    if k in (banda[0], banda[-1]):
        raise EspectroNoDisponible("no se distingue una fundamental clara")
    k_frac, a1 = _refinar_pico(amp, k)
    f1 = float(k_frac * (freqs[1] - freqs[0]))

    ciclos = f1 * n * dt_us * 1e-6
    if ciclos < Config.ESPECTRO_MIN_CICLOS:
        raise EspectroNoDisponible(
            f"la ventana solo tiene {ciclos:.1f} ciclos (mínimo {Config.ESPECTRO_MIN_CICLOS})")

    # 5) armónicos (por debajo de Nyquist con margen)
    h_max = min(Config.ESPECTRO_MAX_ARMONICO,
                int(Config.ESPECTRO_NYQUIST_MARGEN * nyquist // f1))
    if h_max < 2:
        raise EspectroNoDisponible(
            f"fs = {fs:.0f} SPS es muy baja para medir armónicos de {f1:.0f} Hz")

    armonicos = [{"orden": 1, "freq_hz": round(f1, 2), "amp_a": round(a1, 4),
                  "rms_a": round(a1 / math.sqrt(2), 4), "pct_fundamental": 100.0}]
    suma_cuadrados = 0.0
    for h in range(2, h_max + 1):
        idx = np.where(np.abs(freqs - h * f1) <= df_ventana)[0]
        if len(idx) == 0:
            continue
        kh = int(idx[np.argmax(amp[idx])])
        _, ah = _refinar_pico(amp, kh)
        suma_cuadrados += ah * ah
        armonicos.append({"orden": h, "freq_hz": round(h * f1, 2), "amp_a": round(ah, 4),
                          "rms_a": round(ah / math.sqrt(2), 4),
                          "pct_fundamental": round(100.0 * ah / a1, 2)})

    # 6) THD
    thd = 100.0 * math.sqrt(suma_cuadrados) / a1

    f_barras, a_barras = _comprimir_maximos(freqs[freqs <= nyquist], amp[freqs <= nyquist],
                                            Config.ESPECTRO_MAX_BARRAS)
    return {
        "disponible": True,
        "fundamental": {"freq_hz": round(f1, 2), "amp_a": round(a1, 4), "rms_a": round(a1 / math.sqrt(2), 4)},
        "thd_pct": round(thd, 2),
        "thd_nivel": _nivel_thd(thd),
        "armonicos": armonicos,
        "espectro": {"freq_hz": [round(float(v), 2) for v in f_barras],
                     "rms_a": [round(float(v) / math.sqrt(2), 4) for v in a_barras]},
        "muestreo": {"n": n, "fs_hz": round(fs, 1), "nyquist_hz": round(nyquist, 1),
                     "ventana_ms": round(n * dt_us / 1000.0, 2), "ciclos": round(ciclos, 1),
                     "resolucion_hz": round(df_ventana, 2), "armonicos_analizados": h_max,
                     "armonicos_hasta_hz": round(h_max * f1, 1)},
    }
