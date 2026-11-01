#!/usr/bin/env python3
"""Administración de usuarios del dashboard AmpereWatch.

Uso (dentro del contenedor):
  docker compose exec ampere-backend python manage.py create-user admin
  docker compose exec ampere-backend python manage.py set-password admin
  docker compose exec ampere-backend python manage.py delete-user admin
  docker compose exec ampere-backend python manage.py list-users
"""
import argparse
import getpass
import sqlite3
import sys

from app import database as db
from app.auth import hashear, validar_password
from app.services import timestamp_actual


def _pedir_password(username):
    while True:
        p1 = getpass.getpass("Contraseña: ")
        error = validar_password(username, p1)
        if error:
            print(f"❌ {error}")
            continue
        if p1 != getpass.getpass("Repite la contraseña: "):
            print("❌ No coinciden. Intenta de nuevo.")
            continue
        return p1


def crear(args):
    password = _pedir_password(args.username)
    try:
        db.create_user(args.username, hashear(password), timestamp_actual())
    except sqlite3.IntegrityError:
        sys.exit(f"❌ El usuario '{args.username}' ya existe (usa set-password para cambiar su clave).")
    print(f"✅ Usuario '{args.username}' creado.")


def cambiar(args):
    if not db.get_user_by_username(args.username):
        sys.exit(f"❌ El usuario '{args.username}' no existe.")
    db.set_user_password(args.username, hashear(_pedir_password(args.username)))
    print(f"✅ Contraseña actualizada. Las sesiones abiertas de '{args.username}' se cerraron.")


def borrar(args):
    if db.delete_user(args.username):
        print(f"✅ Usuario '{args.username}' eliminado.")
    else:
        sys.exit(f"❌ El usuario '{args.username}' no existe.")


def listar(args):
    usuarios = db.list_users()
    if not usuarios:
        print("(No hay usuarios. Crea uno con: python manage.py create-user NOMBRE)")
    for nombre, creado, ultimo in usuarios:
        print(f"- {nombre:<20} creado: {creado}   último acceso: {ultimo or 'nunca'}")


def main():
    db.init_db()
    parser = argparse.ArgumentParser(description="Administración de usuarios de AmpereWatch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for nombre, fn, ayuda in (("create-user", crear, "Crear usuario"),
                              ("set-password", cambiar, "Cambiar contraseña"),
                              ("delete-user", borrar, "Eliminar usuario")):
        p = sub.add_parser(nombre, help=ayuda)
        p.add_argument("username")
        p.set_defaults(fn=fn)
    sub.add_parser("list-users", help="Listar usuarios").set_defaults(fn=listar)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
