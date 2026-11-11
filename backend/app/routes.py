from flask import Blueprint, jsonify, render_template, request

from config import Config
from app import database as db
from app.auth import csrf_valido
from app.services import (AjusteInvalido, guardar_umbral, obtener_datos_dashboard,
                          obtener_espectro, obtener_umbral)

main_bp = Blueprint("main", __name__)


@main_bp.route("/api/data")
def api_data():
    return jsonify(obtener_datos_dashboard())


@main_bp.route("/api/espectro")
def api_espectro():
    """Análisis espectral (FFT) de la última onda: fundamental, armónicos, THD y espectro para graficar."""
    return jsonify(obtener_espectro())


@main_bp.route("/api/umbral", methods=["POST"])
def api_umbral():
    """Cambia el umbral de sobrecarga. Cuerpo JSON: {"umbral": 12.5}. Requiere sesión y token CSRF."""
    if not csrf_valido():
        return jsonify(error="Token CSRF inválido. Recarga la página."), 403
    cuerpo = request.get_json(silent=True)
    if not isinstance(cuerpo, dict):
        return jsonify(error="Se esperaba un objeto JSON con la clave 'umbral'."), 400
    try:
        nuevo = guardar_umbral(cuerpo.get("umbral"))
    except AjusteInvalido as e:
        return jsonify(error=str(e)), 400
    print(f"⚙️ Umbral de sobrecarga cambiado a {nuevo} A")
    return jsonify(umbral_sobrecarga=nuevo)


@main_bp.route("/")
def index():
    return render_template(
        "dashboard.html",
        total_paquetes_onda=db.count_waveform_packets(),
        reportes=db.get_recent_reports(Config.REPORTES_EN_TABLA),
        umbral=obtener_umbral(),
        umbral_min=Config.UMBRAL_MIN_A,
        umbral_max=Config.CORRIENTE_MAX_A,
    )
