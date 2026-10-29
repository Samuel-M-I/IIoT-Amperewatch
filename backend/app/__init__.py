from flask import Flask
import threading
from app.database import init_db
from app.mqtt_client import start_mqtt_client
from app.routes import main_bp

def create_app():
    app = Flask(__name__)
    
    # Inicializar la base de datos SQLite
    init_db()
    
    # Registrar las rutas (Blueprint)
    app.register_blueprint(main_bp)
    
    return app

def init_mqtt_client(app):
    # Arrancar el cliente MQTT en un hilo en segundo plano para que no bloquee a Flask
    mqtt_thread = threading.Thread(target=start_mqtt_client)
    mqtt_thread.daemon = True
    mqtt_thread.start()
