import os

class Config:
    DATABASE = os.path.join(os.path.dirname(__file__), 'corriente_data.db')
    MQTT_BROKER = os.getenv('MQTT_BROKER', 'mqtt-broker')
    MQTT_PORT = 1883
    TOPIC_RMS = "industrial/amperewatch/rms"
    TOPIC_WAVEFORM = "industrial/amperewatch/waveform"
