import json
import math
from paho.mqtt import client as mqtt_client

from config import Config
from app import database as db
from app.analysis import PaqueteInvalido, analizar_onda, parsear_paquete_onda
from app.spectrum import EspectroNoDisponible, analizar_espectro
from app.services import timestamp_actual, clasificar_estado, limpiar_datos_antiguos

MOTIVOS_RC = {
    1: "versión de protocolo no aceptada",
    2: "identificador de cliente rechazado",
    3: "broker no disponible",
    4: "usuario o contraseña incorrectos",
    5: "no autorizado (revisa usuario/contraseña)",
}


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Conectado de forma segura (TLS) al Broker MQTT desde el Backend.")
        client.subscribe([(Config.TOPIC_RMS, 0), (Config.TOPIC_WAVEFORM, 0)])
    else:
        print(f"❌ El broker rechazó la conexión: {MOTIVOS_RC.get(rc, f'código {rc}')}")


def on_connect_fail(client, userdata):
    print("⚠️ No se pudo establecer la conexión TLS con el broker "
          "(¿broker apagado, CA incorrecta o nombre no incluido en el certificado?). Reintentando...")


def _procesar_rms(datos):
    rms = datos.get("rms") if isinstance(datos, dict) else None
    if isinstance(rms, bool) or not isinstance(rms, (int, float)) or not math.isfinite(rms) \
            or not (0 <= rms <= Config.CORRIENTE_MAX_A):
        raise PaqueteInvalido(f"valor RMS inválido: {rms!r}")
    # La hora la pone el SERVIDOR: la ESP32 no tiene reloj confiable y un equipo con la
    # hora mala corrompería los reportes diarios.
    db.insert_rms(timestamp_actual(), float(rms), clasificar_estado(rms))


def _procesar_onda(datos):
    onda = parsear_paquete_onda(datos)
    metricas = analizar_onda(onda.muestras, onda.t_us)
    try:
        espectro = analizar_espectro(onda.muestras, onda.t_us)
    except EspectroNoDisponible as e:          # ventana corta, sin señal...: se guarda el motivo
        espectro = {"disponible": False, "motivo": str(e)}
    except Exception as e:                     # un fallo del análisis nunca debe perder la onda
        print(f"Error en el análisis espectral: {e}")
        espectro = {"disponible": False, "motivo": "error interno en el análisis espectral"}
    db.insert_waveform(timestamp_actual(), onda.muestras, onda.dt_us, onda.t_irregular, metricas, espectro)
    limpiar_datos_antiguos()


def on_message(client, userdata, msg):
    # Los datos de un dispositivo NO son de confianza: se limita el tamaño y se valida todo.
    if len(msg.payload) > Config.MQTT_MAX_PAYLOAD_BYTES:
        print(f"⚠️ Mensaje descartado en {msg.topic}: {len(msg.payload)} bytes (máx {Config.MQTT_MAX_PAYLOAD_BYTES})")
        return
    try:
        datos = json.loads(msg.payload.decode("utf-8"))
        if msg.topic == Config.TOPIC_RMS:
            _procesar_rms(datos)
        elif msg.topic == Config.TOPIC_WAVEFORM:
            _procesar_onda(datos)
    except (PaqueteInvalido, ValueError) as e:      # incluye JSON mal formado y UnicodeDecodeError
        print(f"⚠️ Mensaje descartado en {msg.topic}: {e}")
    except Exception as e:
        print(f"Error procesando mensaje MQTT en tópico {msg.topic}: {e}")


def start_mqtt_client():
    client = mqtt_client.Client(Config.MQTT_CLIENT_ID)
    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    client.on_message = on_message

    # Cifrado TLS: valida el certificado del broker contra nuestra CA
    # (y que el nombre del broker esté dentro del certificado).
    client.tls_set(ca_certs=Config.MQTT_CA_CERT)

    # Autenticación
    if Config.MQTT_USER:
        client.username_pw_set(Config.MQTT_USER, Config.MQTT_PASSWORD)

    try:
        # connect_async + loop_start: si el broker aún no está listo, paho reintenta solo.
        client.connect_async(Config.MQTT_BROKER, Config.MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"⚠️ No se pudo conectar al broker MQTT: {e}")
    return client
