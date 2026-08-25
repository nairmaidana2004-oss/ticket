"""Administracion de usuarios desde la consola.

    python gestionar_usuarios.py listar
    python gestionar_usuarios.py password <usuario>
    python gestionar_usuarios.py puesto <usuario> "Ventanilla 1"
    python gestionar_usuarios.py crear <usuario> "Nombre Completo" [admin|operador]

La contrasena se pide por teclado y no se muestra en pantalla ni queda en el
historial de comandos.
"""
import getpass
import sys

from app import app
from models import Usuario, db

LARGO_MINIMO = 8


def _pedir_password(usuario):
    while True:
        p1 = getpass.getpass(f"Nueva contrasena para '{usuario}': ")
        if len(p1) < LARGO_MINIMO:
            print(f"  Debe tener al menos {LARGO_MINIMO} caracteres.")
            continue
        p2 = getpass.getpass("Repita la contrasena: ")
        if p1 != p2:
            print("  No coinciden, intente de nuevo.")
            continue
        return p1


def listar():
    usuarios = Usuario.query.order_by(Usuario.rol, Usuario.username).all()
    if not usuarios:
        print("No hay usuarios cargados.")
        return
    print(f"{'USUARIO':<15} {'NOMBRE':<25} {'ROL':<10} {'PUESTO':<18} ESTADO")
    print("-" * 78)
    for u in usuarios:
        estado = 'activo' if u.activo else 'INACTIVO'
        print(f"{u.username:<15} {u.nombre:<25} {u.rol:<10} "
              f"{(u.puesto or '-'):<18} {estado}")


def cambiar_password(username):
    usuario = Usuario.query.filter_by(username=username).first()
    if not usuario:
        print(f"[ERROR] No existe el usuario '{username}'")
        return
    usuario.set_password(_pedir_password(username))
    db.session.commit()
    print(f"[OK] Contrasena actualizada para '{username}'")


def asignar_puesto(username, puesto):
    usuario = Usuario.query.filter_by(username=username).first()
    if not usuario:
        print(f"[ERROR] No existe el usuario '{username}'")
        return
    usuario.puesto = puesto.strip() or None
    db.session.commit()
    print(f"[OK] '{username}' atiende en: {usuario.puesto or '(sin puesto)'}")


def crear(username, nombre, rol='operador'):
    if rol not in ('admin', 'operador'):
        print("[ERROR] El rol debe ser 'admin' u 'operador'")
        return
    if Usuario.query.filter_by(username=username).first():
        print(f"[ERROR] El usuario '{username}' ya existe")
        return
    usuario = Usuario(username=username, nombre=nombre, rol=rol)
    usuario.set_password(_pedir_password(username))
    db.session.add(usuario)
    db.session.commit()
    print(f"[OK] Usuario '{username}' creado con rol {rol}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    comando, argumentos = sys.argv[1], sys.argv[2:]

    with app.app_context():
        if comando == 'listar':
            listar()
        elif comando == 'password' and len(argumentos) == 1:
            cambiar_password(argumentos[0])
        elif comando == 'puesto' and len(argumentos) == 2:
            asignar_puesto(argumentos[0], argumentos[1])
        elif comando == 'crear' and len(argumentos) >= 2:
            crear(argumentos[0], argumentos[1], *argumentos[2:3])
        else:
            print(__doc__)


if __name__ == '__main__':
    main()
