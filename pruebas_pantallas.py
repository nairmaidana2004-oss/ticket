import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
_tmp = os.path.join(tempfile.gettempdir(), 'tiketera_render.db')
if os.path.exists(_tmp):
    os.remove(_tmp)
os.environ['TIKETERA_DATABASE_URI'] = 'sqlite:///' + _tmp.replace('\\', '/')
os.environ['TIKETERA_SECRET_KEY'] = 'clave-de-prueba'

from app import app
from models import Departamento, Ticket, Usuario, db

app.config['TESTING'] = True

with app.app_context():
    db.create_all()
    db.session.add(Departamento(nombre='Creditos', codigo='C'))
    adm = Usuario(username='jefe', nombre='Jefa', rol='admin', puesto='Mesa 1')
    adm.set_password('claveprueba3')
    op = Usuario(username='op', nombre='Ana', rol='operador')  # sin puesto a proposito
    op.set_password('claveprueba1')
    db.session.add_all([adm, op])
    db.session.commit()

fallos = 0
publicas = ['/', '/sala_espera', '/login', '/imprimir_ticket']
privadas = ['/operador']
admin = ['/admin', '/admin/socios', '/admin/usuarios',
         '/admin/departamentos', '/admin/historico']

anon = app.test_client()
print("Paginas publicas:")
for ruta in publicas:
    r = anon.get(ruta)
    ok = r.status_code == 200
    print(f"  {'OK  ' if ok else 'FALLA'} {ruta} ({r.status_code})")
    if not ok:
        fallos += 1

cop = app.test_client()
cop.post('/login', data={'username': 'op', 'password': 'claveprueba1'})
print("Pagina de operador (sin puesto asignado):")
for ruta in privadas:
    r = cop.get(ruta)
    ok = r.status_code == 200
    cuerpo = r.get_data(as_text=True)
    print(f"  {'OK  ' if ok else 'FALLA'} {ruta} ({r.status_code})")
    if not ok:
        fallos += 1
    # El bug de sintaxis JS dentro de Jinja dejaba '${' visible en el HTML
    fuga = '${usuario' in cuerpo
    print(f"  {'OK  ' if not fuga else 'FALLA'} sin plantillas JS crudas en el HTML")
    if fuga:
        fallos += 1
    tiene_aviso = 'Sin puesto asignado' in cuerpo
    print(f"  {'OK  ' if tiene_aviso else 'FALLA'} avisa que falta asignar puesto")
    if not tiene_aviso:
        fallos += 1

cadm = app.test_client()
cadm.post('/login', data={'username': 'jefe', 'password': 'claveprueba3'})
print("Paginas de administracion:")
for ruta in admin:
    r = cadm.get(ruta)
    ok = r.status_code == 200
    print(f"  {'OK  ' if ok else 'FALLA'} {ruta} ({r.status_code})")
    if not ok:
        fallos += 1

print("Operador NO puede entrar a administracion:")
for ruta in admin:
    r = cop.get(ruta)
    ok = r.status_code == 302
    print(f"  {'OK  ' if ok else 'FALLA'} {ruta} -> {r.status_code}")
    if not ok:
        fallos += 1

print("Logo presente en las pantallas:")
for ruta, cliente in [('/', anon), ('/sala_espera', anon), ('/login', anon),
                      ('/operador', cop), ('/admin', cadm)]:
    cuerpo = cliente.get(ruta).get_data(as_text=True)
    ok = 'logo-cooperativa' in cuerpo
    print(f"  {'OK  ' if ok else 'FALLA'} {ruta}")
    if not ok:
        fallos += 1

print("\n" + "=" * 50)
print("TODAS LAS PAGINAS RENDERIZAN OK" if fallos == 0 else f"{fallos} FALLO(S)")
sys.exit(1 if fallos else 0)
