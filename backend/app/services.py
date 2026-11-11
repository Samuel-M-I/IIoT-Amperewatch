"""Lógica de negocio: clasificación, retención, reportes y datos del dashboard."""
import math
import threading
import time
from datetime import datetime, timedelta

from config import Config
from app import database as db


def timestamp_actual():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


CLAVE_UMBRAL = "umbral_sobrecarga"


class AjusteInvalido(ValueError):
    """El valor recibido para un ajuste no es aceptable."""


def obtener_umbral():
    """Umbral de sobrecarga vigente (A): el guardado desde el dashboard o, si no hay, el de config."""
    try:
        valor = float(db.get_setting(CLAVE_UMBRAL))
        if math.isfinite(valor) and valor > 0:
            return valor
    except (TypeError, ValueError):
        pass
    return Config.UMBRAL_SOBRECARGA


def guardar_umbral(valor):
    """Valida y guarda el nuevo umbral. Devuelve el valor guardado; lanza AjusteInvalido si no sirve."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise AjusteInvalido("El umbral debe ser un número.")
    if not (Config.UMBRAL_MIN_A <= valor <= Config.CORRIENTE_MAX_A):
        raise AjusteInvalido(
            f"El umbral debe estar entre {Config.UMBRAL_MIN_A} y {Config.CORRIENTE_MAX_A} A.")
    valor = round(float(valor), 2)
    db.set_setting(CLAVE_UMBRAL, valor, timestamp_actual())
    return valor


def clasificar_estado(corriente_rms):
    return "NORMAL" if corriente_rms < obtener_umbral() else "ALERTA_SOBRECARGA"


def limpiar_datos_antiguos():
    """Elimina paquetes de onda cruda más viejos que la ventana de retención."""
    try:
        limite = datetime.now() - timedelta(hours=Config.WAVEFORM_RETENCION_HORAS)
        db.delete_waveforms_older_than(limite.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        print(f"Error en limpieza de base de datos: {e}")


def generar_reporte_diario():
    """Calcula y guarda las métricas operativas del día (Objetivo 4)."""
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        i_max, i_min, i_prom, sobrecargas, total = db.get_day_summary(hoy)
        if not total:
            return

        horas = total / (3600 * Config.RMS_MUESTRAS_POR_SEGUNDO)
        consumo_kwh = round((i_prom * Config.VOLTAJE_NOMINAL * horas) / 1000, 3)

        db.upsert_daily_report(hoy, round(i_max, 2), round(i_min, 2), round(i_prom, 2),
                               sobrecargas, consumo_kwh)
        print(f"📊 Reporte diario generado para {hoy}: Máx={i_max}A, Prom={i_prom:.2f}A")
    except Exception as e:
        print(f"Error generando reporte diario: {e}")


def iniciar_scheduler_reportes():
    """Recalcula el reporte diario periódicamente en un hilo de fondo."""
    def _loop():
        while True:
            generar_reporte_diario()
            time.sleep(Config.REPORTE_INTERVALO_SEG)

    threading.Thread(target=_loop, daemon=True, name="reportes-diarios").start()


def _edad_segundos(timestamp):
    """Segundos transcurridos desde un timestamp del servidor (None si no se puede interpretar)."""
    try:
        return (datetime.now() - datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")).total_seconds()
    except (TypeError, ValueError):
        return None


def _armar_osciloscopio(onda):
    """Datos listos para dibujar: tiempos en ms, corrientes en A y mediciones."""
    if not onda:
        return None
    n = len(onda["samples"])
    t_us = onda["t_us"] or [k * onda["dt_us"] for k in range(n)]
    edad = _edad_segundos(onda["timestamp"])
    dt = onda["dt_us"]
    metricas = dict(onda["metrics"])
    t_trig = metricas.pop("trigger_us", None)
    return {
        "timestamp": onda["timestamp"],
        "age_s": round(edad, 1) if edad is not None else None,
        "n": n,
        "dt_us": round(dt, 2),
        "fs_real": round(1e6 / dt, 1),                       # frecuencia de muestreo REAL medida
        "t_ms": [round(t / 1000.0, 3) for t in t_us],
        "i": [round(v, 3) for v in onda["samples"]],
        "trigger_ms": round(t_trig / 1000.0, 3) if t_trig is not None else None,
        "timing": "por muestra" if onda["t_us"] else "periodo fijo",
        "metrics": metricas,
    }


def obtener_espectro():
    """Payload JSON de /api/espectro: análisis FFT de la última onda recibida.

    Siempre trae "disponible", "timestamp", "age_s" y "sin_senal_seg". Si disponible es true, además:
    fundamental, thd_pct, thd_nivel, armonicos[], espectro{freq_hz[], rms_a[]} y muestreo{}.
    Si es false, "motivo" explica por qué.
    """
    ultimo = db.get_latest_spectrum()
    if ultimo is None:
        resultado, ts = {"disponible": False, "motivo": "Aún no llegan ondas de la ESP32"}, None
    else:
        ts, esp = ultimo
        resultado = dict(esp) if esp else {"disponible": False, "motivo": "esta onda no tiene análisis espectral"}
    edad = _edad_segundos(ts) if ts else None
    resultado.update(timestamp=ts, age_s=round(edad, 1) if edad is not None else None,
                     sin_senal_seg=Config.SCOPE_SIN_SENAL_SEG)
    return resultado


def obtener_datos_dashboard():
    """Payload JSON de /api/data: historial RMS, osciloscopio y estadísticas del día."""
    historial = [
        {"timestamp": ts, "rms": rms, "estado": estado}
        for ts, rms, estado in db.get_rms_history(Config.HISTORIAL_RMS_GRAFICA)
    ]

    hoy = datetime.now().strftime("%Y-%m-%d")
    i_max, i_min, i_prom, sobrecargas, _ = db.get_day_summary(hoy)

    return {
        "rms_history": historial,
        "scope": _armar_osciloscopio(db.get_latest_waveform()),
        "umbral_sobrecarga": obtener_umbral(),
        "sin_senal_seg": Config.SCOPE_SIN_SENAL_SEG,
        "stats": {
            "i_max": round(i_max, 2) if i_max is not None else 0.0,
            "i_min": round(i_min, 2) if i_min is not None else 0.0,
            "i_prom": round(i_prom, 2) if i_prom is not None else 0.0,
            "sobrecargas": sobrecargas if sobrecargas is not None else 0,
        },
    }
