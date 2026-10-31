import json
from paho.mqtt import client as mqtt_client

from config import Config
from app import database as db
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


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        timestamp = data.get("timestamp", timestamp_actual())

        if msg.topic == Config.TOPIC_RMS:
            corriente_rms = float(data.get("rms", 0.0))
            db.insert_rms(timestamp, corriente_rms, clasificar_estado(corriente_rms))

        elif msg.topic == Config.TOPIC_WAVEFORM:
            db.insert_waveform(timestamp, data.get("samples", []))
            limpiar_datos_antiguos()

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
