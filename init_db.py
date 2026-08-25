"""Inicializacion de la base de datos.

Crea las tablas, los departamentos iniciales y el usuario administrador.
La contrasena del admin se pide por teclado: ya no se crean credenciales
por defecto conocidas.

    python init_db.py
"""
import getpass
import os

from app import app
from models import Departamento, Usuario, db

# Cuatro tonos de brillo parejo, que se distinguen entre si y del fondo verde
DEPARTAMENTOS_INICIALES = [
    ('Créditos', 'C', '#f4c33c', '💰'),          # dorado, el del logo
    ('Atención al Socio', 'A', '#4cc2f0', '🤝'),  # celeste
    ('Tarjeta', 'T', '#f78e5a', '💳'),            # coral
    ('Ahorros', 'AH', '#34d5c0', '🏦'),           # turquesa
]


def _password_admin():
    """Toma la clave de TIKETERA_ADMIN_PASSWORD o la pide por teclado."""
    desde_entorno = os.environ.get('TIKETERA_ADMIN_PASSWORD')
    if desde_entorno:
        if len(desde_entorno) < 8:
            raise SystemExit("[ERROR] TIKETERA_ADMIN_PASSWORD debe tener 8+ caracteres")
        return desde_entorno

    while True:
        p1 = getpass.getpass("Contrasena para el usuario 'admin': ")
        if len(p1) < 8:
            print("  Debe tener al menos 8 caracteres.")
            continue
        if p1 == getpass.getpass("Repita la contrasena: "):
            return p1
        print("  No coinciden, intente de nuevo.")


def init_database():
    with app.app_context():
        db.create_all()
        print("[OK] Tablas verificadas")

        if not Usuario.query.filter_by(username='admin').first():
            admin = Usuario(username='admin', nombre='Administrador', rol='admin')
            admin.set_password(_password_admin())
            db.session.add(admin)
            print("[OK] Usuario 'admin' creado")
        else:
            print("[INFO] El usuario 'admin' ya existe (sin cambios)")

        if not Departamento.query.first():
            for nombre, codigo, color, icono in DEPARTAMENTOS_INICIALES:
                db.session.add(Departamento(
                    nombre=nombre, codigo=codigo, color=color, icono=icono
                ))
            print("[OK] Departamentos creados:")
            for nombre, codigo, _, _ in DEPARTAMENTOS_INICIALES:
                print(f"     - {nombre} ({codigo})")
        else:
            print("[INFO] Ya existen departamentos (sin cambios)")

        db.session.commit()
        print("\n[LISTO] Base de datos inicializada.")
        print("Cree los operadores con:")
        print('  python gestionar_usuarios.py crear jperez "Juan Perez" operador')
        print('  python gestionar_usuarios.py puesto jperez "Ventanilla 1"')


if __name__ == '__main__':
    init_database()
