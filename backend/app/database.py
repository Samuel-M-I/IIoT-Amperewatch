import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '../corriente_data.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabla para lecturas RMS en tiempo real
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rms_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            rms REAL NOT NULL
        )
    ''')
    
    # Tabla para paquetes de forma de onda (60 muestras)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS waveform_packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            samples TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def save_rms(timestamp, rms_value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO rms_readings (timestamp, rms) VALUES (?, ?)', (timestamp, rms_value))
    conn.commit()
    conn.close()

def save_waveform(timestamp, samples_list):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Guardamos las muestras convertidas a una cadena JSON o texto plano separado por comas
    cursor.execute('INSERT INTO waveform_packets (timestamp, samples) VALUES (?, ?)', (timestamp, str(samples_list)))
    conn.commit()
    conn.close()
