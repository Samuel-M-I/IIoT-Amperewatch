import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # --- Base de datos ---
    DATABASE = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "corriente_data.db"))

    # --- MQTT ---
    MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt-broker")
    MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))
    MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "/certs/ca.crt")   # CA que firmó el broker
    MQTT_USER = os.getenv("MQTT_USER")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
    MQTT_CLIENT_ID = "Backend_AmpereWatch"
    TOPIC_RMS = "industrial/amperewatch/rms"
    TOPIC_WAVEFORM = "industrial/amperewatch/waveform"

    # --- Reglas de negocio ---
    UMBRAL_SOBRECARGA = 15.0          # A: por encima de esto => ALERTA_SOBRECARGA
    VOLTAJE_NOMINAL = 120             # V: para el consumo estimado en kWh
    RMS_MUESTRAS_POR_SEGUNDO = 1      # frecuencia a la que llegan lecturas RMS
    WAVEFORM_RETENCION_HORAS = 1      # retención deslizante de ondas crudas
    REPORTE_INTERVALO_SEG = 60        # cada cuánto se recalcula el reporte diario

    # --- Dashboard ---
    HISTORIAL_RMS_GRAFICA = 30        # puntos en la gráfica de tendencia RMS
    REPORTES_EN_TABLA = 5             # filas del histórico de reportes diarios
