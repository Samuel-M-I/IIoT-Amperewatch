"""Autenticación del dashboard: login, logout, sesiones, CSRF y límite de intentos.

Política "denegar por defecto": cualquier ruta nueva que se agregue en el futuro
queda protegida automáticamente. Solo /login y los archivos estáticos son públicos.
"""
import math
import secrets
import threading
import time

from flask import (Blueprint, abort, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from app import database as db
from app.services import timestamp_actual

auth_bp = Blueprint("auth", __name__)

ENDPOINTS_PUBLICOS = {"auth.login", "static"}

# Hash falso: se verifica cuando el usuario no existe para que la respuesta tarde
# lo mismo y no se pueda descubrir qué usuarios existen midiendo tiempos.
_HASH_FALSO = generate_password_hash("contraseña-inexistente")


# ------------------------------------------------------------ política de claves
def validar_password(username, password):
    """Devuelve un mensaje de error, o None si la contraseña es aceptable."""
    if len(password) < Config.PASSWORD_MIN_LARGO:
        return f"La contraseña debe tener al menos {Config.PASSWORD_MIN_LARGO} caracteres."
    if password.lower() == username.lower():
        return "La contraseña no puede ser igual al usuario."
    if password.isdigit():
        return "La contraseña no puede ser solo números."
    return None


def hashear(password):
    return generate_password_hash(password)   # scrypt con sal aleatoria


# ------------------------------------------------------- límite de intentos (por IP)
class LimitadorIntentos:
    def __init__(self):
        self._lock = threading.Lock()
        self._datos = {}   # ip -> {"fallos": [timestamps], "bloqueado_hasta": t}

    def segundos_bloqueado(self, ip):
        ahora = time.time()
        with self._lock:
            d = self._datos.get(ip)
            if d and d["bloqueado_hasta"] > ahora:
                return d["bloqueado_hasta"] - ahora
        return 0

    def registrar_fallo(self, ip):
        ahora = time.time()
        with self._lock:
            d = self._datos.setdefault(ip, {"fallos": [], "bloqueado_hasta": 0})
            d["fallos"] = [t for t in d["fallos"] if ahora - t < Config.LOGIN_VENTANA_SEG]
            d["fallos"].append(ahora)
            if len(d["fallos"]) >= Config.LOGIN_MAX_INTENTOS:
                d["bloqueado_hasta"] = ahora + Config.LOGIN_BLOQUEO_SEG
                d["fallos"] = []
            # limpieza de IPs antiguas
            if len(self._datos) > 1000:
                self._datos = {k: v for k, v in self._datos.items()
                               if v["bloqueado_hasta"] > ahora or v["fallos"]}

    def reiniciar(self, ip):
        with self._lock:
            self._datos.pop(ip, None)


limitador = LimitadorIntentos()


# ------------------------------------------------------------------------ CSRF
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def _csrf_valido():
    enviado = request.form.get("csrf_token", "")
    esperado = session.get("csrf", "")
    return bool(esperado) and secrets.compare_digest(enviado, esperado)


# ---------------------------------------------------------------------- sesiones
def _usuario_en_sesion():
    """La cookie solo guarda un identificador aleatorio; la sesión real vive en la BD.
    Así, cerrar sesión, borrar el usuario o cambiar su contraseña la invalida al instante."""
    sid = session.get("sid")
    if not sid:
        return None
    user = db.get_user_by_session(sid, time.time())
    if user is None:
        session.clear()
    return user


def exigir_login():
    """Se ejecuta antes de CADA petición (before_request)."""
    if request.endpoint in ENDPOINTS_PUBLICOS:
        return None
    user = _usuario_en_sesion()
    if user is None:
        if request.path.startswith("/api/"):
            return jsonify(error="no_autenticado"), 401
        return redirect(url_for("auth.login"))
    g.user = user
    return None


# ------------------------------------------------------------------------ rutas
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if _usuario_en_sesion():
            return redirect(url_for("main.index"))
        return render_template("login.html")

    if not _csrf_valido():
        abort(400)

    ip = request.remote_addr or "desconocida"
    espera = limitador.segundos_bloqueado(ip)
    if espera:
        minutos = max(1, math.ceil(espera / 60))
        return render_template(
            "login.html", error=f"Demasiados intentos fallidos. Espera {minutos} min."), 429

    username = request.form.get("username", "").strip()[:64]
    password = request.form.get("password", "")[:256]

    user = db.get_user_by_username(username)
    hash_a_verificar = user["password_hash"] if user else _HASH_FALSO
    correcto = check_password_hash(hash_a_verificar, password) and user is not None

    if not correcto:
        limitador.registrar_fallo(ip)
        print(f"🔒 Login fallido desde {ip} para el usuario {username!r}")
        return render_template("login.html", error="Usuario o contraseña incorrectos."), 401

    limitador.reiniciar(ip)
    session.clear()                     # evita fijación de sesión
    session.permanent = True
    ahora = time.time()
    sid = secrets.token_urlsafe(32)
    db.create_session(sid, user["id"], ahora + Config.PERMANENT_SESSION_LIFETIME.total_seconds(), ahora)
    session["sid"] = sid
    session["csrf"] = secrets.token_urlsafe(32)      # token CSRF listo desde el primer momento
    db.update_last_login(user["id"], timestamp_actual())
    print(f"🔓 Login correcto: {user['username']!r} desde {ip}")
    return redirect(url_for("main.index"))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    if not _csrf_valido():
        abort(400)
    if session.get("sid"):
        db.delete_session(session["sid"])      # revoca la sesión en el servidor
    session.clear()
    return redirect(url_for("auth.login"))
