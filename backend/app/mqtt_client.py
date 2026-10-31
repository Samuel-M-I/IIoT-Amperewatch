import json
from paho.mqtt import client as mqtt_client

from config import Config
from app import database as db
from app.services import timestamp_actual, clasificar_estado, limpiar_datos_antiguos


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Conectado exitosamente al Broker MQTT desde el Backend.")
        client.subscribe([(Config.TOPIC_RMS, 0), (Config.TOPIC_WAVEFORM, 0)])
    else:
        print(f"❌ Error al conectar al broker MQTT, código de retorno: {rc}")


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
    client.on_message = on_message

    try:
        # connect_async + loop_start: si el broker aún no está listo, paho reintenta solo.
        client.connect_async(Config.MQTT_BROKER, Config.MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"⚠️ No se pudo conectar al broker MQTT: {e}")
    return client
