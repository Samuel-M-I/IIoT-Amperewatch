"""Capa de acceso a datos (SQLite). Ninguna otra parte del código escribe SQL."""
import json
import sqlite3
from contextlib import contextmanager

from config import Config


@contextmanager
def db_cursor(commit=False):
    conn = sqlite3.connect(Config.DATABASE)
    try:
        yield conn.cursor()
        if commit:
            conn.commit()
    finally:
        conn.close()


def _migrar_esquema_antiguo(cursor):
    """La primera versión modular usaba otras columnas (rms / samples).
    Como son datos simulados, se descartan esas tablas para recrearlas bien."""
    for tabla, columna_antigua in (("rms_readings", "rms"), ("waveform_packets", "samples")):
        cursor.execute(f"PRAGMA table_info({tabla})")
        columnas = [fila[1] for fila in cursor.fetchall()]
        if columna_antigua in columnas:
            print(f"⚠️ Esquema antiguo detectado en '{tabla}'. Se recreará la tabla.")
            cursor.execute(f"DROP TABLE {tabla}")


def init_db():
    with db_cursor(commit=True) as cursor:
        _migrar_esquema_antiguo(cursor)

        # Histórico de RMS
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rms_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                corriente_rms REAL,
                estado TEXT
            )
        ''')

        # Paquetes de forma de onda en tiempo real
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS waveform_packets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                samples_json TEXT
            )
        ''')

        # Reportes diarios consolidados (Objetivo 4)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT UNIQUE,
                i_max REAL,
                i_min REAL,
                i_prom REAL,
                total_sobrecargas INTEGER,
                consumo_estimado_kwh REAL
            )
        ''')


# ---------------------------------------------------------------- escritura
def insert_rms(timestamp, corriente_rms, estado):
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            "INSERT INTO rms_readings (timestamp, corriente_rms, estado) VALUES (?, ?, ?)",
            (timestamp, corriente_rms, estado),
        )


def insert_waveform(timestamp, samples):
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            "INSERT INTO waveform_packets (timestamp, samples_json) VALUES (?, ?)",
            (timestamp, json.dumps(samples)),
        )


def delete_waveforms_older_than(cutoff_timestamp):
    with db_cursor(commit=True) as cursor:
        cursor.execute("DELETE FROM waveform_packets WHERE timestamp < ?", (cutoff_timestamp,))


def upsert_daily_report(fecha, i_max, i_min, i_prom, total_sobrecargas, consumo_kwh):
    with db_cursor(commit=True) as cursor:
        cursor.execute('''
            INSERT OR REPLACE INTO daily_reports
                (fecha, i_max, i_min, i_prom, total_sobrecargas, consumo_estimado_kwh)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (fecha, i_max, i_min, i_prom, total_sobrecargas, consumo_kwh))


# ----------------------------------------------------------------- lectura
def get_rms_history(limit):
    """Devuelve las últimas `limit` lecturas en orden cronológico."""
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT timestamp, corriente_rms, estado FROM rms_readings ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return list(reversed(cursor.fetchall()))


def get_day_summary(fecha):
    """(max, min, avg, sobrecargas, total_muestras) del día indicado (YYYY-MM-DD)."""
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT MAX(corriente_rms), MIN(corriente_rms), AVG(corriente_rms),
                   SUM(CASE WHEN estado = 'ALERTA_SOBRECARGA' THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM rms_readings
            WHERE timestamp LIKE ?
        ''', (f"{fecha}%",))
        return cursor.fetchone()


def get_latest_waveform():
    with db_cursor() as cursor:
        cursor.execute("SELECT samples_json FROM waveform_packets ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
    return json.loads(row[0]) if row else []


def count_waveform_packets():
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM waveform_packets")
        return cursor.fetchone()[0]


def get_recent_reports(limit):
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT fecha, i_max, i_min, i_prom, total_sobrecargas, consumo_estimado_kwh
            FROM daily_reports ORDER BY id DESC LIMIT ?
        ''', (limit,))
        return cursor.fetchall()
