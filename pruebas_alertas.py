"""Prueba las alertas de cola y el horario de atencion.

Corre sobre una base temporal y manipula la hora simulada, para poder probar
el cierre sin esperar a que sean las 17:00.

    python pruebas_alertas.py
"""
import os
import sys
import tempfile
from datetime import datetime, time as dtime, timedelta

_TMP = os.path.join(tempfile.gettempdir(), 'tiketera_alertas.db')
if os.path.exists(_TMP):
    os.remove(_TMP)
os.environ['TIKETERA_DATABASE_URI'] = 'sqlite:///' + _TMP.replace('\\', '/')
os.environ['TIKETERA_SECRET_KEY'] = 'clave-de-prueba'
os.environ['TIKETERA_ALERTA_ESPERA'] = '20'
os.environ['TIKETERA_ALERTA_COLA'] = '10'

import app as modulo                                    # noqa: E402
from app import app, estado_horario                     # noqa: E402
from config import LOCAL_TZ                             # noqa: E402
from models import Departamento, Ticket, Usuario, db, utcnow   # noqa: E402

fallos = []


def check(nombre, ok, detalle=''):
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre} {detalle}")
    if not ok:
        fallos.append(nombre)


app.config['TESTING'] = True
with app.app_context():
    db.create_all()
    creditos = Departamento(nombre='Créditos', codigo='C', color='#f4c33c')
    atencion = Departamento(nombre='Atención al Socio', codigo='A', color='#4cc2f0')
    db.session.add_all([creditos, atencion])
    u = Usuario(username='op', nombre='Ana', rol='operador', puesto='Ventanilla 1')
    u.set_password('claveprueba1')
    db.session.add(u)
    db.session.commit()
    id_creditos, id_atencion = creditos.id, atencion.id

cliente = app.test_client()
cliente.post('/login', data={'username': 'op', 'password': 'claveprueba1'})


def crear_turnos(dep_id, cantidad, minutos_atras=0):
    with app.app_context():
        for i in range(cantidad):
            db.session.add(Ticket(
                numero=i + 1, codigo_completo=f'X-{i:03d}', departamento_id=dep_id,
                estado=Ticket.PENDIENTE,
                fecha_creacion=utcnow() - timedelta(minutes=minutos_atras)))
        db.session.commit()


print("\n[1] Sin cola no hay alerta")
r = cliente.get('/api/alertas')
datos = r.get_json()
check('responde', r.status_code == 200)
check('no hay alerta', datos['hay_alerta'] is False)
check('informa los umbrales configurados',
      datos['umbral_espera'] == 20 and datos['umbral_cola'] == 10)

print("\n[2] Cola corta y reciente: tampoco")
crear_turnos(id_atencion, 3, minutos_atras=4)
datos = cliente.get('/api/alertas').get_json()
check('sigue sin alerta', datos['hay_alerta'] is False)
a = next(c for c in datos['colas'] if c['departamento'] == 'Atención al Socio')
check('igual informa la cola', a['en_espera'] == 3, f"({a['en_espera']})")

print("\n[3] Alguien esperando mas del umbral -> alerta por ESPERA")
crear_turnos(id_creditos, 2, minutos_atras=26)
datos = cliente.get('/api/alertas').get_json()
c = next(x for x in datos['colas'] if x['departamento'] == 'Créditos')
check('se dispara la alerta', datos['hay_alerta'] is True)
check('el motivo es la espera', 'espera' in c['motivos'], f"({c['motivos']})")
check('mide la espera maxima', c['espera_maxima'] >= 25, f"({c['espera_maxima']} min)")
check('la cola en alerta va primero', datos['colas'][0]['departamento'] == 'Créditos')

print("\n[4] Muchos en cola -> alerta por CANTIDAD")
crear_turnos(id_atencion, 9, minutos_atras=2)
datos = cliente.get('/api/alertas').get_json()
a = next(x for x in datos['colas'] if x['departamento'] == 'Atención al Socio')
check('12 personas superan el umbral de 10', a['en_espera'] == 12, f"({a['en_espera']})")
check('el motivo es la cantidad', 'cola' in a['motivos'], f"({a['motivos']})")
check('no marca espera, porque son recientes', 'espera' not in a['motivos'])

print("\n[5] Un anonimo no ve las colas")
check('sin sesion da 401', app.test_client().get('/api/alertas').status_code == 401)

# ---------------------------------------------------------------- horario
print("\n[6] Horario de atención")
app.config['HORARIO_ACTIVO'] = True
app.config['HORARIO'] = {0: '07:00-17:00', 1: '07:00-17:00', 2: '07:00-17:00',
                         3: '07:00-17:00', 4: '07:00-17:00', 5: '07:00-12:00',
                         6: ''}
app.config['CORTE_ANTES_DEL_CIERRE'] = 15

# 2026-08-24 es lunes; 2026-08-30, domingo
def momento(fecha, hora):
    return datetime.combine(fecha, hora, tzinfo=LOCAL_TZ)


from datetime import date                               # noqa: E402
LUNES, SABADO, DOMINGO = date(2026, 8, 24), date(2026, 8, 29), date(2026, 8, 30)

casos = [
    (momento(LUNES, dtime(6, 30)), False, 'antes_de_abrir', 'lunes 06:30'),
    (momento(LUNES, dtime(9, 0)), True, None, 'lunes 09:00'),
    (momento(LUNES, dtime(16, 44)), True, None, 'lunes 16:44'),
    (momento(LUNES, dtime(16, 50)), False, 'por_cerrar', 'lunes 16:50 (por cerrar)'),
    (momento(LUNES, dtime(17, 30)), False, 'cerrado', 'lunes 17:30'),
    (momento(SABADO, dtime(10, 0)), True, None, 'sabado 10:00'),
    (momento(SABADO, dtime(13, 0)), False, 'cerrado', 'sabado 13:00'),
    (momento(DOMINGO, dtime(10, 0)), False, 'cerrado_hoy', 'domingo'),
]
for cuando, emite, motivo, etiqueta in casos:
    with app.app_context():
        h = estado_horario(cuando)
    ok = h['emite'] is emite and h['motivo'] == motivo
    check(f"{etiqueta:<28} emite={str(emite):<5}", ok,
          f"-> emite={h['emite']}, motivo={h['motivo']}")

print("\n[7] El servidor rechaza turnos fuera de horario")
original = modulo.estado_horario
try:
    modulo.estado_horario = lambda ahora=None: {
        'abierto': False, 'emite': False, 'motivo': 'cerrado',
        'apertura': '07:00', 'cierre': '17:00', 'proximo': 'mañana 07:00'}
    r = app.test_client().post('/api/tickets', json={'departamento_id': id_creditos})
    check('devuelve 409', r.status_code == 409, f"(dio {r.status_code})")
    check('marca fuera_de_horario', r.get_json().get('fuera_de_horario') is True)
    check('explica cuando volver', 'mañana 07:00' in r.get_json().get('error', ''),
          f"-> {r.get_json().get('error')}")
finally:
    modulo.estado_horario = original

print("\n[8] Con el horario apagado se emite a cualquier hora")
app.config['HORARIO_ACTIVO'] = False
with app.app_context():
    h = estado_horario(momento(DOMINGO, dtime(3, 0)))
check('un domingo a las 3 AM emite igual', h['emite'] is True)
r = app.test_client().post('/api/tickets', json={'departamento_id': id_creditos})
check('el turno se emite', r.status_code == 201, f"(dio {r.status_code})")

print("\n" + "=" * 62)
if fallos:
    print(f"RESULTADO: {len(fallos)} fallo(s):")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("RESULTADO: alertas de cola y horario funcionan")
