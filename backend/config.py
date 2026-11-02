import os
from datetime import timedelta

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

    # --- Paquetes de forma de onda (ESP32 + ADS1115) ---
    MQTT_MAX_PAYLOAD_BYTES = 65536    # mensajes más grandes se descartan sin procesar
    ONDA_MIN_MUESTRAS = 16
    ONDA_MAX_MUESTRAS = 2048
    ONDA_DT_MIN_US = 20               # periodo de muestreo plausible: 20 us (50 kSPS)...
    ONDA_DT_MAX_US = 100000           # ...hasta 100 ms (10 SPS)
    CORRIENTE_MAX_A = 1000            # cualquier muestra por encima se considera dato corrupto
    FREQ_MIN_AMP_A = 0.05             # por debajo de esta amplitud pico no se intenta medir frecuencia
    FREQ_HISTERESIS = 0.10            # banda anti-ruido del detector de cruces (fracción de Ip)
    SCOPE_SIN_SENAL_SEG = 5           # sin paquetes de onda por más de esto => "sin señal"

    # --- Dashboard ---
    HISTORIAL_RMS_GRAFICA = 50        # puntos en la gráfica de tendencia RMS
    REPORTES_EN_TABLA = 5             # filas del histórico de reportes diarios

    # --- Seguridad web (login + sesiones) ---
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY")       # obligatoria; la genera scripts/setup_security.sh
    SESSION_COOKIE_NAME = "amperewatch_session"
    SESSION_COOKIE_HTTPONLY = True                   # el JavaScript no puede leer la cookie
    SESSION_COOKIE_SAMESITE = "Lax"                  # protección extra contra CSRF
    # Solo viaja por HTTPS. Para pruebas sin HTTPS: SESSION_COOKIE_SECURE=false
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.getenv("SESSION_HORAS", 8)))
    CONFIAR_EN_PROXY = os.getenv("CONFIAR_EN_PROXY", "true").lower() == "true"   # nginx delante

    LOGIN_MAX_INTENTOS = 5          # fallos permitidos...
    LOGIN_VENTANA_SEG = 600         # ...dentro de esta ventana (10 min)
    LOGIN_BLOQUEO_SEG = 300         # bloqueo de la IP (5 min)
    PASSWORD_MIN_LARGO = 10
