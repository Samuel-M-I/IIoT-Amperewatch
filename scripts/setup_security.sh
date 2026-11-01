#!/usr/bin/env bash
# AmpereWatch - Genera certificados TLS (broker MQTT y web), contraseñas y claves secretas.
#
# Uso:
#   ./scripts/setup_security.sh [--dns NOMBRE]... [--ip DIRECCION]... [--new-passwords]
#
# Ejemplos:
#   ./scripts/setup_security.sh --dns amperewatch.local --ip 192.168.18.50
#   ./scripts/setup_security.sh --new-passwords      (rota las contraseñas)
#
# - La CA (ca.key) se guarda FUERA del proyecto, en $CA_DIR (por defecto ~/amperewatch-ca).
# - Se puede volver a ejecutar cuando quieras (p.ej. para añadir un nombre o una IP al certificado).
#   La CA se reutiliza, así que los equipos que ya confían en ca.crt siguen funcionando.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERTS_DIR="$ROOT/certs"
CONF_DIR="$ROOT/mosquitto/config"
ENV_FILE="$ROOT/.env"
CA_DIR="${CA_DIR:-$HOME/amperewatch-ca}"
BROKER_UID="${BROKER_UID:-1883}"            # usuario con el que corre mosquitto en Docker
MOSQ_IMAGE="${MOSQ_IMAGE:-eclipse-mosquitto:latest}"

DNS_NAMES=("mqtt-broker" "localhost")
IP_ADDRS=("127.0.0.1")
NEW_PASSWORDS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dns) DNS_NAMES+=("$2"); shift 2 ;;
    --ip)  IP_ADDRS+=("$2");  shift 2 ;;
    --new-passwords) NEW_PASSWORDS=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1"; exit 1 ;;
  esac
done

command -v openssl >/dev/null || { echo "❌ Falta openssl"; exit 1; }
mkdir -p "$CERTS_DIR" "$CA_DIR"
chmod 700 "$CA_DIR"

# ------------------------------------------------------------------ 1. CA
if [[ ! -f "$CA_DIR/ca.key" || ! -f "$CA_DIR/ca.crt" ]]; then
  echo "🔐 Creando la Autoridad Certificadora (CA) en $CA_DIR ..."
  openssl genrsa -out "$CA_DIR/ca.key" 4096 2>/dev/null
  chmod 600 "$CA_DIR/ca.key"
  openssl req -x509 -new -nodes -key "$CA_DIR/ca.key" -sha256 -days 3650 \
    -subj "/CN=AmpereWatch CA/O=AmpereWatch" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -out "$CA_DIR/ca.crt"
else
  echo "🔐 Reutilizando la CA existente en $CA_DIR"
fi

# ------------------------------------------------- 2. Certificado del broker
SAN=""
for d in "${DNS_NAMES[@]}"; do SAN+="DNS:$d,"; done
for i in "${IP_ADDRS[@]}";  do SAN+="IP:$i,";  done
SAN="${SAN%,}"

echo "📜 Generando certificado del broker. Nombres válidos: $SAN"
rm -f "$CERTS_DIR"/server.key "$CERTS_DIR"/server.crt "$CERTS_DIR"/server.csr \
      "$CERTS_DIR"/web.key "$CERTS_DIR"/web.crt "$CERTS_DIR"/web.csr \
      "$CERTS_DIR"/ca.key "$CERTS_DIR"/ca.srl "$CERTS_DIR"/ca.crt
openssl genrsa -out "$CERTS_DIR/server.key" 2048 2>/dev/null
openssl req -new -key "$CERTS_DIR/server.key" -subj "/CN=mqtt-broker/O=AmpereWatch" \
  -out "$CERTS_DIR/server.csr"
openssl x509 -req -in "$CERTS_DIR/server.csr" \
  -CA "$CA_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" -CAserial "$CA_DIR/ca.srl" -CAcreateserial \
  -days 825 -sha256 \
  -extfile <(printf "subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n" "$SAN") \
  -out "$CERTS_DIR/server.crt" 2>/dev/null
rm -f "$CERTS_DIR/server.csr"
cp "$CA_DIR/ca.crt" "$CERTS_DIR/ca.crt"          # solo el certificado público de la CA
openssl verify -CAfile "$CERTS_DIR/ca.crt" "$CERTS_DIR/server.crt" >/dev/null
echo "   ✅ server.crt (broker MQTT) firmado y verificado contra la CA"

# Certificado del servidor WEB (HTTPS del dashboard): llave propia, misma CA y mismos nombres.
# 397 días: el límite que aceptan todos los navegadores. Vuelve a ejecutar el script cada año.
openssl genrsa -out "$CERTS_DIR/web.key" 2048 2>/dev/null
openssl req -new -key "$CERTS_DIR/web.key" -subj "/CN=amperewatch-web/O=AmpereWatch" \
  -out "$CERTS_DIR/web.csr"
openssl x509 -req -in "$CERTS_DIR/web.csr" \
  -CA "$CA_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" -CAserial "$CA_DIR/ca.srl" -CAcreateserial \
  -days 397 -sha256 \
  -extfile <(printf "subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n" "$SAN") \
  -out "$CERTS_DIR/web.crt" 2>/dev/null
rm -f "$CERTS_DIR/web.csr"
openssl verify -CAfile "$CERTS_DIR/ca.crt" "$CERTS_DIR/web.crt" >/dev/null
echo "   ✅ web.crt (HTTPS del dashboard) firmado y verificado contra la CA"

# ------------------------------------------------------- 3. Contraseñas (.env)
if [[ ! -f "$ENV_FILE" || $NEW_PASSWORDS -eq 1 ]]; then
  echo "🔑 Generando contraseñas aleatorias en .env"
  cat > "$ENV_FILE" << ENVEOF
MQTT_BACKEND_USER=backend
MQTT_BACKEND_PASSWORD=$(openssl rand -hex 16)
MQTT_DEVICE_USER=esp32
MQTT_DEVICE_PASSWORD=$(openssl rand -hex 16)
ENVEOF
  chmod 600 "$ENV_FILE"
else
  echo "🔑 Se conserva el .env existente (usa --new-passwords para rotar)"
fi
# Clave secreta de Flask (firma las cookies de sesión). Se añade si falta, sin tocar lo demás.
if ! grep -q '^FLASK_SECRET_KEY=' "$ENV_FILE"; then
  echo "🔑 Generando FLASK_SECRET_KEY en .env"
  echo "FLASK_SECRET_KEY=$(openssl rand -hex 32)" >> "$ENV_FILE"
fi
set -a; source "$ENV_FILE"; set +a

# ------------------------------------------- 4. Archivo de usuarios del broker
echo "👤 Creando usuarios del broker: $MQTT_BACKEND_USER y $MQTT_DEVICE_USER"
rm -f "$CONF_DIR/passwd"
if command -v mosquitto_passwd >/dev/null; then
  mosquitto_passwd -b -c "$CONF_DIR/passwd" "$MQTT_BACKEND_USER" "$MQTT_BACKEND_PASSWORD"
  mosquitto_passwd -b    "$CONF_DIR/passwd" "$MQTT_DEVICE_USER"  "$MQTT_DEVICE_PASSWORD"
else
  command -v docker >/dev/null || { echo "❌ Hace falta mosquitto_passwd o docker"; exit 1; }
  docker run --rm -u "$(id -u):$(id -g)" -v "$CONF_DIR:/work" "$MOSQ_IMAGE" \
    mosquitto_passwd -b -c /work/passwd "$MQTT_BACKEND_USER" "$MQTT_BACKEND_PASSWORD"
  docker run --rm -u "$(id -u):$(id -g)" -v "$CONF_DIR:/work" "$MOSQ_IMAGE" \
    mosquitto_passwd -b /work/passwd "$MQTT_DEVICE_USER" "$MQTT_DEVICE_PASSWORD"
fi

# ------------------------------------------- 4b. Permisos por topic (acl)
[[ -f "$CONF_DIR/acl.template" ]] || { echo "❌ Falta $CONF_DIR/acl.template"; exit 1; }
rm -f "$CONF_DIR/acl"                       # puede pertenecer a otro usuario; borrar no requiere sudo
cp "$CONF_DIR/acl.template" "$CONF_DIR/acl"

# -------------------------------------------------------------- 5. Permisos
# Archivos que lee el broker (corre como uid 1883 dentro de Docker): dueño 1883 y modo 600.
# Como pueden pertenecer ya a 1883 (de una ejecución anterior), se cambian con sudo.
chmod 644 "$CERTS_DIR/ca.crt" "$CERTS_DIR/server.crt" "$CERTS_DIR/web.crt"
chmod 600 "$CERTS_DIR/web.key"              # solo lo lee nginx (corre como root en su contenedor)

# Archivos secretos del broker: deben ser del usuario con el que corre mosquitto en Docker.
ARCHIVOS_BROKER=("$CERTS_DIR/server.key" "$CONF_DIR/passwd" "$CONF_DIR/acl")
if [[ "${SKIP_CHOWN:-0}" == "1" ]]; then
  chmod 600 "${ARCHIVOS_BROKER[@]}"
else
  echo "🛡️  Dando al usuario del broker (uid $BROKER_UID) acceso a sus archivos secretos (pide sudo)..."
  sudo chown "$BROKER_UID:$BROKER_UID" "${ARCHIVOS_BROKER[@]}" \
    && sudo chmod 600 "${ARCHIVOS_BROKER[@]}" \
    || echo "⚠️  No se pudo. Ejecútalo a mano: sudo chown $BROKER_UID:$BROKER_UID certs/server.key mosquitto/config/passwd mosquitto/config/acl && sudo chmod 600 certs/server.key mosquitto/config/passwd mosquitto/config/acl"
fi

echo
FP="$(openssl x509 -in "$CERTS_DIR/ca.crt" -noout -fingerprint -sha256 | cut -d= -f2)"
echo "✅ Listo. Siguiente paso:  docker compose up -d --build --force-recreate"
echo "   🔎 Huella SHA-256 de tu CA (compárala al instalarla en un navegador/celular):"
echo "      $FP"
echo "   ⚠️  Guarda una copia de $CA_DIR/ca.key en un lugar seguro (NO en el proyecto ni en GitHub)."
