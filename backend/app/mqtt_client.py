import json
import os
from paho.mqtt import client as mqtt_client
from app.database import save_rms, save_waveform

BROKER = os.getenv('MQTT_BROKER', 'mqtt-broker')
PORT = 1883
TOPIC_RMS = "industrial/amperewatch/rms"
TOPIC_WAVEFORM = "industrial/amperewatch/waveform"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Conectado exitosamente al Broker MQTT desde el Backend.")
        client.subscribe(TOPIC_RMS)
        client.subscribe(TOPIC_WAVEFORM)
    else:
        print(f"❌ Error al conectar al broker MQTT, código de retorno: {rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        timestamp = payload.get('timestamp')

        if msg.topic == TOPIC_RMS:
            rms_val = payload.get('rms')
            if rms_val is not None:
                save_rms(timestamp, rms_val)
                print(f"[BD] RMS guardado: {rms_val} A")

        elif msg.topic == TOPIC_WAVEFORM:
            samples = payload.get('samples')
            if samples is not None:
                save_waveform(timestamp, samples)
                print(f"[BD] Paquete de onda (60 muestras) guardado.")

    except Exception as e:
        print(f"⚠️ Error procesando mensaje MQTT: {e}")

def start_mqtt_client():
    client = mqtt_client.Client("Backend_AmpereWatch")
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(BROKER, PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"⚠️ No se pudo conectar al broker MQTT: {e}")
