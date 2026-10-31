"""Lógica de negocio: clasificación, retención, reportes y datos del dashboard."""
import threading
import time
from datetime import datetime, timedelta

from config import Config
from app import database as db


def timestamp_actual():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def clasificar_estado(corriente_rms):
    return "NORMAL" if corriente_rms < Config.UMBRAL_SOBRECARGA else "ALERTA_SOBRECARGA"


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


def obtener_datos_dashboard():
    """Payload JSON de /api/data: historial RMS, última onda y estadísticas del día."""
    historial = [
        {"timestamp": ts, "rms": rms, "estado": estado}
        for ts, rms, estado in db.get_rms_history(Config.HISTORIAL_RMS_GRAFICA)
    ]

    hoy = datetime.now().strftime("%Y-%m-%d")
    i_max, i_min, i_prom, sobrecargas, _ = db.get_day_summary(hoy)

    return {
        "rms_history": historial,
        "latest_waveform": db.get_latest_waveform(),
        "stats": {
            "i_max": round(i_max, 2) if i_max is not None else 0.0,
            "i_min": round(i_min, 2) if i_min is not None else 0.0,
            "i_prom": round(i_prom, 2) if i_prom is not None else 0.0,
            "sobrecargas": sobrecargas if sobrecargas is not None else 0,
        },
    }
