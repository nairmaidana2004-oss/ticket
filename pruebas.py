import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
_tmp = os.path.join(tempfile.gettempdir(), 'tiketera_smoke.db')
if os.path.exists(_tmp):
    os.remove(_tmp)
os.environ['TIKETERA_DATABASE_URI'] = 'sqlite:///' + _tmp.replace('\\', '/')
os.environ['TIKETERA_SECRET_KEY'] = 'clave-de-prueba-solo-para-el-test'

from app import app
from models import Departamento, Socio, Ticket, Usuario, db

fallos = []


def check(nombre, condicion, detalle=''):
    if condicion:
        print(f"  OK   {nombre}")
    else:
        print(f"  FALLA {nombre} {detalle}")
        fallos.append(nombre)


app.config['TESTING'] = True

with app.app_context():
    db.create_all()
    dep = Departamento(nombre='Creditos', codigo='C', color='#8b5cf6', icono='C')
    db.session.add(dep)
    a = Usuario(username='op1', nombre='Ana', rol='operador', puesto='Ventanilla 1')
    a.set_password('claveprueba1')
    b = Usuario(username='op2', nombre='Beto', rol='operador', puesto='Ventanilla 2')
    b.set_password('claveprueba2')
    adm = Usuario(username='jefe', nombre='Jefa', rol='admin')
    adm.set_password('claveprueba3')
    db.session.add_all([a, b, adm])
    db.session.add(Socio(numero_socio='1042', dni='1234567', nombre='Carlos',
                         apellido='Gimenez', telefono='0981000000', email='c@x.com'))
    db.session.commit()
    dep_id = dep.id

anon = app.test_client()

print("\n[1] Endpoints publicos siguen abiertos")
check('GET /api/departamentos', anon.get('/api/departamentos').status_code == 200)
check('GET /api/tickets/llamado', anon.get('/api/tickets/llamado').status_code == 200)
check('GET /api/tickets/llamados', anon.get('/api/tickets/llamados').status_code == 200)
check('GET /api/estadisticas', anon.get('/api/estadisticas').status_code == 200)
check('GET / (kiosco)', anon.get('/').status_code == 200)
check('GET /sala_espera', anon.get('/sala_espera').status_code == 200)

print("\n[2] La API de socios ya NO es publica")
check('GET /api/socios -> 401', anon.get('/api/socios').status_code == 401,
      f"(dio {anon.get('/api/socios').status_code})")
check('POST /api/socios -> 401',
      anon.post('/api/socios', json={'dni': '9', 'nombre': 'X', 'apellido': 'Y'}).status_code == 401)
check('PUT /api/socios/1 -> 401', anon.put('/api/socios/1', json={}).status_code == 401)
check('DELETE /api/socios/1 -> 401', anon.delete('/api/socios/1').status_code == 401)
check('GET /api/socios/count -> 401', anon.get('/api/socios/count').status_code == 401)
check('GET /api/tickets/pendientes -> 401', anon.get('/api/tickets/pendientes').status_code == 401)
check('GET /api/tickets/historico -> 401', anon.get('/api/tickets/historico').status_code == 401)

print("\n[3] Busqueda de socio en el kiosco: N de socio y nombre, sin datos de contacto")
r = anon.get('/api/socios/buscar?dni=1234567')
datos = r.get_json()
check('devuelve el socio', r.status_code == 200 and datos and datos.get('nombre') == 'Carlos')
check('devuelve el N de socio', (datos or {}).get('numero_socio') == '1042',
      f"(dio {(datos or {}).get('numero_socio')})")
check('devuelve nombre y apellido',
      (datos or {}).get('nombre') == 'Carlos' and (datos or {}).get('apellido') == 'Gimenez')
check('NO expone telefono', 'telefono' not in (datos or {}))
check('NO expone email', 'email' not in (datos or {}))
check('NO expone dni', 'dni' not in (datos or {}))

print("\n[4] /socio redirige al kiosco en vez de romper con 500")
r = anon.get('/socio')
check('/socio -> 302 al kiosco', r.status_code == 302 and r.headers['Location'].endswith('/'),
      f"(dio {r.status_code})")

print("\n[5] Numeracion por departamento sin exponer datos del socio")
codigos = []
for i in range(3):
    r = anon.post('/api/tickets', json={'departamento_id': dep_id,
                                        'nombre_socio': 'Carlos Gimenez',
                                        'dni_socio': '1234567'})
    codigos.append(r.get_json()['codigo_completo'])
check('numeracion correlativa', codigos == ['C-001', 'C-002', 'C-003'], f"(dio {codigos})")
check('el kiosco no recibe dni_socio', 'dni_socio' not in r.get_json())
check('fecha con zona horaria', r.get_json()['fecha_creacion'].endswith('+00:00'))

print("\n[5b] El ticket de un socio guarda N de socio, documento y nombre")
r = anon.post('/api/tickets', json={'departamento_id': dep_id,
                                    'dni_socio': '1234567',
                                    'numero_socio': 'inventado-999',
                                    'nombre_socio': 'Nombre Falso'})
check('el kiosco no recibe de vuelta el N de socio', 'numero_socio' not in r.get_json())
with app.app_context():
    t = Ticket.query.filter_by(codigo_completo=r.get_json()['codigo_completo']).first()
    guardado = (t.numero_socio, t.dni_socio, t.nombre_socio)
check('toma el N de socio del padron, no del kiosco', guardado[0] == '1042',
      f"(guardo {guardado[0]})")
check('guarda el documento', guardado[1] == '1234567')
check('toma el nombre del padron', guardado[2] == 'Carlos Gimenez', f"(guardo {guardado[2]})")

print("\n[6] Dos operadores atienden en paralelo sin pisarse")
c1, c2 = app.test_client(), app.test_client()
c1.post('/login', data={'username': 'op1', 'password': 'claveprueba1'})
c2.post('/login', data={'username': 'op2', 'password': 'claveprueba2'})

t1 = c1.post('/api/tickets/siguiente', json={}).get_json()
t2 = c2.post('/api/tickets/siguiente', json={}).get_json()
check('op1 llama C-001', t1['codigo_completo'] == 'C-001', f"(dio {t1.get('codigo_completo')})")
check('op2 llama C-002', t2['codigo_completo'] == 'C-002', f"(dio {t2.get('codigo_completo')})")
check('op1 en Ventanilla 1', t1['puesto_atencion'] == 'Ventanilla 1')
check('op2 en Ventanilla 2', t2['puesto_atencion'] == 'Ventanilla 2')

llamados = anon.get('/api/tickets/llamados').get_json()
check('la TV muestra AMBOS llamados a la vez', len(llamados) == 2,
      f"(muestra {len(llamados)})")
check('la TV no expone datos del socio',
      all('dni_socio' not in t and 'nombre_socio' not in t for t in llamados))

with app.app_context():
    pend = Ticket.query.filter_by(estado='Pendiente').count()
    total_emitidos = Ticket.query.count()
# Se emitieron 4 turnos y hay 2 llamados: los otros 2 deben seguir en la cola.
check('los turnos no llamados siguen pendientes (nadie los devolvio a la cola)',
      pend == total_emitidos - 2, f"(pendientes={pend} de {total_emitidos})")

print("\n[7] Un operador no puede robar el ticket de otro")
with app.app_context():
    id_de_op2 = Ticket.query.filter_by(codigo_completo='C-002').first().id
r = c1.put(f'/api/tickets/{id_de_op2}/llamar')
check('op1 llamando el ticket de op2 -> 409', r.status_code == 409, f"(dio {r.status_code})")

print("\n[8] Al llamar el siguiente, se cierra solo lo propio")
t3 = c1.post('/api/tickets/siguiente', json={}).get_json()
check('op1 pasa a C-003', t3['codigo_completo'] == 'C-003')
with app.app_context():
    est1 = Ticket.query.filter_by(codigo_completo='C-001').first().estado
    est2 = Ticket.query.filter_by(codigo_completo='C-002').first().estado
check('C-001 (de op1) quedo Finalizado', est1 == 'Finalizado', f"(dio {est1})")
check('C-002 (de op2) sigue Llamado', est2 == 'Llamado', f"(dio {est2})")

print("\n[9] Reiniciar numeracion NO borra tickets")
r = c1.post('/api/tickets/reiniciar', json={})
check('operador no puede reiniciar -> 403', r.status_code == 403, f"(dio {r.status_code})")

cadm = app.test_client()
cadm.post('/login', data={'username': 'jefe', 'password': 'claveprueba3'})
with app.app_context():
    total_antes = Ticket.query.count()
r = cadm.post('/api/tickets/reiniciar', json={})
check('admin puede reiniciar -> 200', r.status_code == 200, f"(dio {r.status_code})")
with app.app_context():
    total = Ticket.query.count()
check('los tickets del dia se conservan', total == total_antes,
      f"(habia {total_antes}, quedan {total})")
nuevo = anon.post('/api/tickets', json={'departamento_id': dep_id}).get_json()
check('el contador volvio a C-001', nuevo['codigo_completo'] == 'C-001',
      f"(dio {nuevo['codigo_completo']})")

print("\n[10] Open redirect en el login")
r = anon.post('/login?next=//sitio-externo.com',
              data={'username': 'op1', 'password': 'claveprueba1'})
destino = r.headers.get('Location', '')
check('no redirige a sitio externo', 'sitio-externo.com' not in destino, f"(fue a {destino})")

print("\n[11] Validaciones de usuarios")
r = cadm.post('/api/usuarios', json={'username': 'x', 'nombre': 'X', 'password': 'corta'})
check('contrasena corta rechazada', r.status_code == 400)
r = cadm.post('/api/usuarios', json={'username': 'x', 'nombre': 'X',
                                     'password': 'buenaclave1', 'rol': 'superroot'})
check('rol invalido rechazado', r.status_code == 400, f"(dio {r.status_code})")

print("\n" + "=" * 60)
if fallos:
    print(f"RESULTADO: {len(fallos)} prueba(s) fallaron:")
    for f in fallos:
        print(f"  - {f}")
    sys.exit(1)
print("RESULTADO: todas las pruebas pasaron")
