import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime
import random
import math
import os

# Configuración del Broker (TLS + usuario/contraseña, desde variables de entorno)
BROKER = os.getenv("MQTT_BROKER", "mqtt-broker")
PORT = int(os.getenv("MQTT_PORT", 8883))
CA_CERT = os.getenv("MQTT_CA_CERT", "/certs/ca.crt")
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

TOPIC_RMS = "industrial/amperewatch/rms"
TOPIC_WAVEFORM = "industrial/amperewatch/waveform"

# Inicialización compatible con paho-mqtt v2.0+
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "Simulador_ESP32")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("🔒 Simulador autenticado y conectado por TLS al Broker MQTT.")
    else:
        print(f"❌ El broker rechazó al simulador (código {rc}). Revisa usuario/contraseña.")


client.on_connect = on_connect
client.tls_set(ca_certs=CA_CERT)
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

try:
    client.connect(BROKER, PORT, 60)
    client.loop_start()
    print("🚀 Simulador de Motor (ESP32) iniciando...")

    contador = 0
    fase_arranque = True
    ciclos_arranque = 10  # Los primeros 10 segundos simulan el pico de arranque del motor
    
    while True:
        timestamp_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # 1. Simulación de corriente RMS realista para un motor
        if ciclos_arranque > 0:
            # Pico de arranque alto decayendo progresivamente
            rms_valor = round(random.uniform(35.0, 45.0) - (10 - ciclos_arranque) * 2.2, 2)
            ciclos_arranque -= 1
        else:
            # Operación normal con carga variable pequeña (ej: nominal en ~12.5A)
            rms_valor = round(12.5 + random.uniform(-1.5, 1.5), 2)

        rms_data = {
            "timestamp": timestamp_actual,
            "rms": max(rms_valor, 1.0)
        }
        client.publish(TOPIC_RMS, json.dumps(rms_data))
        print(f"[{timestamp_actual}] RMS Motor: {rms_data['rms']} A")

        # 2. Cada 5 iteraciones, enviar un paquete de onda sinusoidal de 60 muestras
        contador += 1
        if contador >= 5:
            # Generar 60 muestras de una onda senoidal simulada con un poco de ruido industrial
            amplitud_pico = rms_data['rms'] * math.sqrt(2) # Relación RMS a Pico
            muestras = [
                round(amplitud_pico * math.sin(2 * math.pi * i / 60) + random.uniform(-0.8, 0.8), 2)
                for i in range(60)
            ]

            waveform_data = {
                "timestamp": timestamp_actual,
                "samples": muestras
            }
            client.publish(TOPIC_WAVEFORM, json.dumps(waveform_data))
            print("--> Paquete de onda de corriente (60 muestras) enviado.")
            contador = 0

        # Frecuencia de envío de datos RMS (1 vez por segundo)
        time.sleep(1)

except KeyboardInterrupt:
    print("\nSimulación detenida por el usuario.")
    client.loop_stop()
    client.disconnect()
