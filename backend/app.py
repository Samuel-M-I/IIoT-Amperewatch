import os
import sqlite3
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string
import paho.mqtt.client as mqtt

app = Flask(__name__)
DB_PATH = "corriente_data.db"

# --- Inicialización de Base de Datos con Doble Tabla, Retención y Reportes ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabla 1: Histórico de RMS (Consolidado a 10 Hz)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rms_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            corriente_rms REAL,
            estado TEXT
        )
    ''')
    
    # Tabla 2: Paquetes de forma de onda en tiempo real (Bloques de 50 muestras)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS waveform_packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            samples_json TEXT
        )
    ''')

    # Tabla 3: Reportes diarios consolidados (Objetivo 4)
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
    
    conn.commit()
    conn.close()

init_db()

def limpiar_datos_antiguos():
    """Elimina los paquetes de ondas crudas mayores a 1 hora (Retención deslizante)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        hace_una_hora = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("DELETE FROM waveform_packets WHERE timestamp < ?", (hace_una_hora,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error en limpieza de base de datos: {e}")

def generar_reporte_diario_automatico():
    """Calcula las métricas operativas del día (Objetivo 4)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        hoy = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute('''
            SELECT MAX(corriente_rms), MIN(corriente_rms), AVG(corriente_rms),
                   SUM(CASE WHEN estado = 'ALERTA_SOBRECARGA' THEN 1 ELSE 0 END),
                   COUNT(*) 
            FROM rms_readings 
            WHERE timestamp LIKE ?
        ''', (f"{hoy}%",))
        
        row = cursor.fetchone()
        if row and row[4] > 0:
            i_max, i_min, i_prom, total_sobrecargas, total_muestras = row
            consumo_estimado = round((i_prom * 120 * (total_muestras / 3600)) / 1000, 3)
            
            cursor.execute('''
                INSERT OR REPLACE INTO daily_reports (fecha, i_max, i_min, i_prom, total_sobrecargas, consumo_estimado_kwh)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (hoy, round(i_max, 2), round(i_min, 2), round(i_prom, 2), total_sobrecargas, consumo_estimado))
            conn.commit()
            print(f"📊 Reporte diario generado para {hoy}: Máx={i_max}A, Prom={i_prom}A")
        conn.close()
    except Exception as e:
        print(f"Error generando reporte diario: {e}")

# --- Configuración del Cliente MQTT ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt-broker")
MQTT_PORT = 1883

TOPIC_RMS = "industrial/amperewatch/rms"
TOPIC_WAVEFORM = "industrial/amperewatch/waveform"

def on_connect(client, userdata, flags, rc):
    print(f"Conectado al Broker MQTT con código: {rc}")
    client.subscribe([(TOPIC_RMS, 0), (TOPIC_WAVEFORM, 0)])

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        
        if msg.topic == TOPIC_RMS:
            data = json.loads(payload)
            timestamp = data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])
            corriente_rms = float(data.get("rms", 0.0))
            estado = "NORMAL" if corriente_rms < 15.0 else "ALERTA_SOBRECARGA"

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO rms_readings (timestamp, corriente_rms, estado) VALUES (?, ?, ?)",
                           (timestamp, corriente_rms, estado))
            conn.commit()
            conn.close()

        elif msg.topic == TOPIC_WAVEFORM:
            data = json.loads(payload)
            timestamp = data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])
            samples = data.get("samples", [])
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO waveform_packets (timestamp, samples_json) VALUES (?, ?)",
                           (timestamp, json.dumps(samples)))
            conn.commit()
            conn.close()

            limpiar_datos_antiguos()

    except Exception as e:
        print(f"Error procesando mensaje MQTT en tópico {msg.topic}: {e}")

# Iniciar cliente MQTT en segundo plano
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"No se pudo conectar al broker MQTT: {e}")

# --- Rutas API REST para el Dashboard Interactivo ---
@app.route('/api/data')
def api_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Últimos 30 registros RMS para alimentar la gráfica en tiempo real
    cursor.execute("SELECT timestamp, corriente_rms, estado FROM rms_readings ORDER BY id DESC LIMIT 30")
    filas = cursor.fetchall()
    
    # Calcular estadísticas en tiempo real del día actual para las tarjetas de resumen
    hoy = datetime.now().strftime("%Y-%m-%d")
    cursor.execute('''
        SELECT MAX(corriente_rms), MIN(corriente_rms), AVG(corriente_rms),
               SUM(CASE WHEN estado = 'ALERTA_SOBRECARGA' THEN 1 ELSE 0 END)
        FROM rms_readings 
        WHERE timestamp LIKE ?
    ''', (f"{hoy}%",))
    stats = cursor.fetchone()
    
    # Último paquete de forma de onda disponible
    cursor.execute("SELECT samples_json FROM waveform_packets ORDER BY id DESC LIMIT 1")
    wf_row = cursor.fetchone()
    conn.close()
    
    data_rms = [{"timestamp": r[0], "rms": r[1], "estado": r[2]} for r in reversed(filas)]
    samples = json.loads(wf_row[0]) if wf_row else []
    
    # Valores estadísticos actuales del día
    i_max_val = round(stats[0], 2) if stats[0] is not None else 0.0
    i_min_val = round(stats[1], 2) if stats[1] is not None else 0.0
    i_prom_val = round(stats[2], 2) if stats[2] is not None else 0.0
    sobrecargas_val = stats[3] if stats[3] is not None else 0
    
    return jsonify({
        "rms_history": data_rms,
        "latest_waveform": samples,
        "stats": {
            "i_max": i_max_val,
            "i_min": i_min_val,
            "i_prom": i_prom_val,
            "sobrecargas": sobrecargas_val
        }
    })

# --- Ruta Principal del Dashboard con Chart.js ---
@app.route('/')
def index():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, corriente_rms, estado FROM rms_readings ORDER BY id DESC LIMIT 15")
    registros_rms = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) FROM waveform_packets")
    total_paquetes_onda = cursor.fetchone()[0]

    cursor.execute("SELECT fecha, i_max, i_min, i_prom, total_sobrecargas, consumo_estimado_kwh FROM daily_reports ORDER BY id DESC LIMIT 5")
    reportes = cursor.fetchall()
    conn.close()

    html_template = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>AmpereWatch IIoT Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 20px; }
            h1, h2 { color: #333; }
            .card { background: white; padding: 15px; margin-bottom: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }
            .metric-card { background: white; padding: 15px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }
            .metric-card h3 { margin: 0 0 10px 0; font-size: 14px; color: #666; }
            .metric-card p { margin: 0; font-size: 24px; font-weight: bold; color: #007bff; }
            .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
            table { width: 100%; border-collapse: collapse; background: white; margin-top: 10px; }
            th, td { padding: 8px; border: 1px solid #ddd; text-align: center; font-size: 14px; }
            th { background: #007bff; color: white; }
            .ALERTA_SOBRECARGA { background: #ffcccc; color: #900; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>AmpereWatch: Monitoreo IIoT Industrial</h1>
        <div class="card">
            <p>Estado del Servidor: <strong>Activo y Conectado (MQTT & Flask)</strong></p>
            <p>Paquetes de forma de onda (última hora en búfer): <strong>{{ total_paquetes_onda }}</strong></p>
        </div>

        <!-- Tarjetas de Métricas en Tiempo Real (Actualizadas por JS) -->
        <div class="metrics-grid">
            <div class="metric-card">
                <h3>Corriente Promedio (Hoy)</h3>
                <p id="stat-prom">0.00 A</p>
            </div>
            <div class="metric-card">
                <h3>Corriente Máxima (Hoy)</h3>
                <p id="stat-max">0.00 A</p>
            </div>
            <div class="metric-card">
                <h3>Corriente Mínima (Hoy)</h3>
                <p id="stat-min">0.00 A</p>
            </div>
            <div class="metric-card">
                <h3>Eventos Sobrecarga</h3>
                <p id="stat-overload" style="color: #dc3545;">0</p>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h3>Tendencia Corriente RMS (A)</h3>
                <canvas id="rmsChart"></canvas>
            </div>
            <div class="card">
                <h3>Forma de Onda en Tiempo Real (50 muestras)</h3>
                <canvas id="waveformChart"></canvas>
            </div>
        </div>

        <div class="card">
            <h2>Histórico de Reportes Diarios (Objetivo 4)</h2>
            <table>
                <tr><th>Fecha</th><th>Máx (A)</th><th>Mín (A)</th><th>Prom (A)</th><th>Sobrecargas</th><th>kWh Est.</th></tr>
                {% for rep in reportes %}
                <tr>
                    <td>{{ rep[0] }}</td><td>{{ rep[1] }}</td><td>{{ rep[2] }}</td>
                    <td>{{ rep[3] }}</td><td>{{ rep[4] }}</td><td>{{ rep[5] }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>

        <script>
            const ctxRms = document.getElementById('rmsChart').getContext('2d');
            const rmsChart = new Chart(ctxRms, {
                type: 'line',
                data: { labels: [], datasets: [{ label: 'Corriente RMS (A)', data: [], borderColor: '#007bff', tension: 0.1 }] },
                options: { responsive: true, scales: { y: { beginAtZero: true, suggestedMax: 25 } } }
            });

            const ctxWf = document.getElementById('waveformChart').getContext('2d');
            const waveformChart = new Chart(ctxWf, {
                type: 'line',
                data: { labels: Array.from({length: 50}, (_, i) => i+1), datasets: [{ label: 'Muestras ADC', data: [], borderColor: '#28a745', tension: 0.2 }] },
                options: { responsive: true }
            });

            function actualizarDatos() {
                fetch('/api/data')
                    .then(response => response.json())
                    .then(data => {
                        // Actualizar gráficas
                        rmsChart.data.labels = data.rms_history.map(item => item.timestamp.split(' ')[1]);
                        rmsChart.data.datasets[0].data = data.rms_history.map(item => item.rms);
                        rmsChart.update();

                        if (data.latest_waveform.length > 0) {
                            waveformChart.data.datasets[0].data = data.latest_waveform;
                            waveformChart.update();
                        }

                        // Actualizar tarjetas de métricas en tiempo real
                        document.getElementById('stat-prom').innerText = data.stats.i_prom.toFixed(2) + ' A';
                        document.getElementById('stat-max').innerText = data.stats.i_max.toFixed(2) + ' A';
                        document.getElementById('stat-min').innerText = data.stats.i_min.toFixed(2) + ' A';
                        document.getElementById('stat-overload').innerText = data.stats.sobrecargas;
                    });
            }

            setInterval(actualizarDatos, 1000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, total_paquetes_onda=total_paquetes_onda, reportes=reportes)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
