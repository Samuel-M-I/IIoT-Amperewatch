"""Validación de paquetes de forma de onda y mediciones tipo osciloscopio.

Python puro (sin numpy) para mantener la imagen Docker liviana en la Raspberry.

IMPORTANTE sobre el tiempo: el reloj interno del ADS1115 tiene una tolerancia de ±10 %
(y varía con temperatura y voltaje). Por eso la ESP32 debe medir con micros() cuándo
tomó cada muestra y enviarlo en `t_us`; asumir "860 SPS" daría una frecuencia errónea.
"""
import math
from collections import namedtuple

from config import Config

# muestras: lista de float (A) | t_us: tiempos en µs desde la 1ª muestra
# dt_us: periodo medio de muestreo | t_irregular: lista original de t_us, o None si es regular
Onda = namedtuple("Onda", "muestras t_us dt_us t_irregular")


class PaqueteInvalido(ValueError):
    """El paquete no cumple el formato o trae datos imposibles."""


def _numero(valor, campo):
    # bool es subclase de int en Python: se rechaza explícitamente
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise PaqueteInvalido(f"'{campo}' contiene un valor no numérico o no finito")
    return float(valor)


def parsear_paquete_onda(datos):
    """Valida el JSON recibido por MQTT y devuelve una `Onda` normalizada.

    Formato (ver docs/PROTOCOLO_MQTT.md):
      samples : lista de corrientes en amperios            (obligatorio)
      t_us    : instante de cada muestra en µs             \\
      dt_us   : periodo de muestreo en µs                   > uno de los tres
      fs      : frecuencia de muestreo en Hz               /   (t_us es el más preciso)
    """
    if not isinstance(datos, dict):
        raise PaqueteInvalido("el mensaje debe ser un objeto JSON")

    crudas = datos.get("samples")
    if not isinstance(crudas, list):
        raise PaqueteInvalido("'samples' debe ser una lista")
    n = len(crudas)
    if not (Config.ONDA_MIN_MUESTRAS <= n <= Config.ONDA_MAX_MUESTRAS):
        raise PaqueteInvalido(
            f"nº de muestras fuera de rango ({n}; permitido {Config.ONDA_MIN_MUESTRAS}-{Config.ONDA_MAX_MUESTRAS})")

    muestras = [_numero(v, "samples") for v in crudas]
    if any(abs(v) > Config.CORRIENTE_MAX_A for v in muestras):
        raise PaqueteInvalido(f"muestra fuera de rango (|I| > {Config.CORRIENTE_MAX_A} A)")

    t_irregular = None
    if datos.get("t_us") is not None:
        t_raw = datos["t_us"]
        if not isinstance(t_raw, list) or len(t_raw) != n:
            raise PaqueteInvalido("'t_us' debe ser una lista con el mismo largo que 'samples'")
        t = [_numero(v, "t_us") for v in t_raw]
        t0 = t[0]
        t = [v - t0 for v in t]                        # relativo a la primera muestra
        if any(b <= a for a, b in zip(t, t[1:])):
            raise PaqueteInvalido("'t_us' debe ser estrictamente creciente")
        dt = t[-1] / (n - 1)
        t_irregular = t
    elif datos.get("dt_us") is not None:
        dt = _numero(datos["dt_us"], "dt_us")
        t = [k * dt for k in range(n)]
    elif datos.get("fs") is not None:
        fs = _numero(datos["fs"], "fs")
        if fs <= 0:
            raise PaqueteInvalido("'fs' debe ser positiva")
        dt = 1e6 / fs
        t = [k * dt for k in range(n)]
    else:
        raise PaqueteInvalido("falta información de tiempo: envía 't_us', 'dt_us' o 'fs'")

    if not (Config.ONDA_DT_MIN_US <= dt <= Config.ONDA_DT_MAX_US):
        raise PaqueteInvalido(f"periodo de muestreo fuera de rango ({dt:.1f} µs)")

    return Onda(muestras, t, dt, t_irregular)


def _cruces_ascendentes(x, t, nivel, histeresis):
    """Cruces de `nivel` en sentido ascendente, con disparador de Schmitt (anti-ruido).
    Devuelve [(tiempo_interpolado_us, indice_primera_muestra_posterior), ...]."""
    cruces = []
    armado = False
    for k in range(1, len(x)):
        if x[k - 1] < nivel - histeresis:
            armado = True
        if armado and x[k - 1] < nivel <= x[k]:
            frac = (nivel - x[k - 1]) / (x[k] - x[k - 1])
            cruces.append((t[k - 1] + frac * (t[k] - t[k - 1]), k))
            armado = False
    return cruces


def analizar_onda(muestras, t_us):
    """Mediciones de una ventana de corriente (como las de un osciloscopio).

    irms  : valor eficaz (sobre un nº entero de ciclos si se detecta la frecuencia)
    ip    : amplitud pico = (Imax - Imin) / 2
    imax, imin, ipp : extremos de la ventana y pico a pico
    idc   : componente continua (offset), medida en ciclos completos -> ~0 si el sensor está bien calibrado
    freq  : Hz (None si no hay ≥ 2 cruces claros)
    crest : factor de cresta = |pico| / irms
    """
    n = len(muestras)
    imax, imin = max(muestras), min(muestras)
    ip = (imax - imin) / 2.0
    idc = sum(muestras) / n
    irms = math.sqrt(sum(v * v for v in muestras) / n)      # respaldo: toda la ventana

    freq = None
    ciclos = 0
    trigger_us = None

    if ip >= Config.FREQ_MIN_AMP_A:
        nivel = (imax + imin) / 2.0
        cruces = _cruces_ascendentes(muestras, t_us, nivel, Config.FREQ_HISTERESIS * ip)
        if len(cruces) >= 2:
            ciclos = len(cruces) - 1
            freq = ciclos / (cruces[-1][0] - cruces[0][0]) * 1e6
            trigger_us = cruces[0][0]
            k0, k1 = cruces[0][1], cruces[-1][1]
            segmento = muestras[k0:k1]
            if segmento:   # RMS y offset sobre ciclos COMPLETOS: los ciclos partidos los falsean
                irms = math.sqrt(sum(v * v for v in segmento) / len(segmento))
                idc = sum(segmento) / len(segmento)

    pico_abs = max(abs(imax), abs(imin))
    crest = (pico_abs / irms) if irms > 1e-6 else None

    r = lambda v, d=3: None if v is None else round(v, d)
    return {
        "irms": r(irms), "ip": r(ip), "imax": r(imax), "imin": r(imin),
        "ipp": r(imax - imin), "idc": r(idc),
        "freq": r(freq, 2), "crest": r(crest, 2),
        "ciclos": ciclos, "trigger_us": r(trigger_us, 1),
    }
