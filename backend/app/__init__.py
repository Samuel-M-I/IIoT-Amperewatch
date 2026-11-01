from flask import Flask, request
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from app.auth import auth_bp, csrf_token, exigir_login
from app.database import init_db
from app.mqtt_client import start_mqtt_client
from app.routes import main_bp
from app.services import iniciar_scheduler_reportes

# Todo se sirve desde nuestro propio servidor (sin CDNs externos).
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not Config.SECRET_KEY or len(Config.SECRET_KEY) < 32:
        raise RuntimeError(
            "Falta FLASK_SECRET_KEY (mínimo 32 caracteres). "
            "Ejecuta ./scripts/setup_security.sh para generarla en el .env")

    # Detrás de nginx: toma la IP real y el esquema https de las cabeceras X-Forwarded-*
    if Config.CONFIAR_EN_PROXY:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    init_db()
    app.before_request(exigir_login)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.after_request
    def cabeceras_de_seguridad(resp):
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        if request.endpoint != "static":      # datos sensibles: que el navegador no los guarde
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app


def init_mqtt_client(app):
    """Arranca el cliente MQTT (paho ya usa su propio hilo con loop_start)."""
    app.mqtt_client = start_mqtt_client()


def init_scheduler(app):
    """Arranca el hilo que genera los reportes diarios."""
    iniciar_scheduler_reportes()
