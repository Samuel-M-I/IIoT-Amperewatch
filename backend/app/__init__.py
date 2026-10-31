from flask import Flask

from config import Config
from app.database import init_db
from app.mqtt_client import start_mqtt_client
from app.routes import main_bp
from app.services import iniciar_scheduler_reportes


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db()
    app.register_blueprint(main_bp)
    return app


def init_mqtt_client(app):
    """Arranca el cliente MQTT (paho ya usa su propio hilo con loop_start)."""
    app.mqtt_client = start_mqtt_client()


def init_scheduler(app):
    """Arranca el hilo que genera los reportes diarios."""
    iniciar_scheduler_reportes()
