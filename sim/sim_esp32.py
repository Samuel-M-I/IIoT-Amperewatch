"""Simulador de la ESP32 + ADS1115 + sensor de corriente de un motor trifásico/monofásico.

Imita lo que hará el equipo real:
  * ADS1115 a 860 SPS NOMINALES, pero con el error de reloj real del chip (±10 %, aquí fijo
    por "unidad" y con una pequeña deriva): la ESP32 mide cada muestra con micros().
  * Ventana de N muestras cada segundo (≈ 9 ciclos de 60 Hz con N=128).
  * Frecuencia de red que varía un poco, ruido, armónicos 3º/5º y pequeño offset.
Publica en los mismos topics que el equipo real (ver docs/PROTOCOLO_MQTT.md).
"""
import json
import math
import os
import random
import time

import paho.mqtt.client as mqtt

# Configuración del Broker (TLS + usuario/contraseña, desde variables de entorno)
BROKER = os.getenv("MQTT_BROKER", "mqtt-broker")
PORT = int(os.getenv("MQTT_PORT", 8883))
CA_CERT = os.getenv("MQTT_CA_CERT", "/certs/ca.crt")
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

TOPIC_RMS = "industrial/amperewatch/rms"
TOPIC_WAVEFORM = "industrial/amperewatch/waveform"

# --- Parámetros del "hardware" simulado ---
FS_NOMINAL = 860                 # SPS configurados en el ADS1115
N_MUESTRAS = int(os.getenv("SIM_N_MUESTRAS", 128))
ERROR_RELOJ = random.uniform(-0.07, 0.07)   # el reloj real del ADS1115 nunca es exacto
JITTER_US = 15                   # incertidumbre de micros()/interrupción por muestra
PERIODO_ENVIO_S = float(os.getenv("SIM_PERIODO_S", 1.0))

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


def corriente_rms_objetivo(segundo, arranque_restante):
    """Perfil de un motor: arranque con pico alto que decae y luego régimen normal."""
    if arranque_restante > 0:
        return random.uniform(35.0, 45.0) - (10 - arranque_restante) * 2.2
    return 12.5 + random.uniform(-1.5, 1.5)


def generar_ventana(irms, frecuencia, fase0, t_inicio_s):
    """N muestras como las vería el ADS1115. Devuelve (muestras_A, t_us, fase_final)."""
    dt_real_us = 1e6 / (FS_NOMINAL * (1.0 + ERROR_RELOJ + random.uniform(-0.002, 0.002)))
    norm = math.sqrt(1 + 0.06 ** 2 + 0.03 ** 2)
    muestras, t_us = [], []
    for k in range(N_MUESTRAS):
        t = k * dt_real_us + random.gauss(0, JITTER_US)            # lo que mediría micros()
        w = fase0 + 2 * math.pi * frecuencia * t / 1e6
        v = (math.sin(w) + 0.06 * math.sin(3 * w + 0.7) + 0.03 * math.sin(5 * w + 1.3)) / norm
        muestras.append(round(math.sqrt(2) * irms * v + 0.03 + random.gauss(0, 0.06), 3))
        t_us.append(int(round(t)))
    t_us[0] = 0
    for k in range(1, N_MUESTRAS):                                  # estrictamente creciente
        if t_us[k] <= t_us[k - 1]:
            t_us[k] = t_us[k - 1] + 1
    fase_fin = fase0 + 2 * math.pi * frecuencia * (N_MUESTRAS * dt_real_us) / 1e6
    return muestras, t_us, fase_fin % (2 * math.pi)


try:
    client.connect(BROKER, PORT, 60)
    client.loop_start()
    print(f"🚀 Simulador ESP32+ADS1115: {N_MUESTRAS} muestras/ventana, {FS_NOMINAL} SPS nominales "
          f"(error de reloj simulado: {ERROR_RELOJ * 100:+.1f} %)")

    segundo = 0
    arranque = 10          # los primeros 10 s simulan el pico de arranque del motor
    fase = 0.0
    while True:
        irms_obj = max(corriente_rms_objetivo(segundo, arranque), 1.0)
        if arranque > 0:
            arranque -= 1
        f_red = 60.0 + 0.15 * math.sin(segundo / 20.0) + random.gauss(0, 0.02)

        muestras, t_us, fase = generar_ventana(irms_obj, f_red, fase, segundo)

        # RMS de la propia ventana: el valor que reportaría el firmware (coherente con el osciloscopio)
        rms = round(math.sqrt(sum(v * v for v in muestras) / len(muestras)), 2)
        client.publish(TOPIC_RMS, json.dumps({"rms": rms}))
        client.publish(TOPIC_WAVEFORM, json.dumps({"fs": FS_NOMINAL, "samples": muestras, "t_us": t_us}))
        print(f"[t={segundo:>4}s] RMS Motor: {rms} A | f_red={f_red:.2f} Hz | "
              f"ventana {len(muestras)} muestras en {t_us[-1] / 1000:.1f} ms")

        segundo += 1
        time.sleep(PERIODO_ENVIO_S)

except KeyboardInterrupt:
    print("\nSimulación detenida por el usuario.")
    client.loop_stop()
    client.disconnect()
