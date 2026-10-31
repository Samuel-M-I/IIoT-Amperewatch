from flask import Blueprint, jsonify, render_template

from config import Config
from app import database as db
from app.services import obtener_datos_dashboard

main_bp = Blueprint("main", __name__)


@main_bp.route("/api/data")
def api_data():
    return jsonify(obtener_datos_dashboard())


@main_bp.route("/")
def index():
    return render_template(
        "dashboard.html",
        total_paquetes_onda=db.count_waveform_packets(),
        reportes=db.get_recent_reports(Config.REPORTES_EN_TABLA),
    )
