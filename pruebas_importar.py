"""Prueba el importador del padron sobre una base temporal.

Arma un archivo con los errores tipicos de un export real (cedulas con puntos,
filas vacias, duplicados) y verifica que los detecte y no ensucie la base.

    python pruebas_importar.py
"""
import csv
import io
import os
import subprocess
import sys
import tempfile

_TMP = os.path.join(tempfile.gettempdir(), 'tiketera_importar.db')
if os.path.exists(_TMP):
    os.remove(_TMP)
os.environ['TIKETERA_DATABASE_URI'] = 'sqlite:///' + _TMP.replace('\\', '/')
os.environ['TIKETERA_SECRET_KEY'] = 'clave-de-prueba'

from app import app                                    # noqa: E402
from models import Socio, db                           # noqa: E402

fallos = []


def check(nombre, ok, detalle=''):
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre} {detalle}")
    if not ok:
        fallos.append(nombre)


CABECERAS = ['Nro Socio', 'Cedula', 'Apellidos', 'Nombres', 'Telefono']
FILAS = [
    ['1001', '2.500.812', 'Villalba', 'Gustavo', '0980670440'],   # con puntos
    ['1002', '1276114', 'Duarte', 'Anibal', ''],
    ['1003', '6029538', 'Ferreira', 'Miguel', ''],
    ['', '3874512', 'Gonzalez', 'Pedro', ''],                     # sin N de socio
    ['1005', '', 'Sin', 'Cedula', ''],                            # se descarta
    ['1006', '123', 'Cedula', 'Corta', ''],                       # se descarta
    ['1007', '1276114', 'Repetida', 'Cedula', ''],                # se descarta
    ['1008', '5550001', '', '', ''],                              # se descarta
    ['1001', '5550002', 'Numero', 'Repetido', ''],                # se descarta
]

carpeta = tempfile.mkdtemp()
ruta_csv = os.path.join(carpeta, 'padron.csv')
with io.open(ruta_csv, 'w', encoding='cp1252', newline='') as f:
    w = csv.writer(f, delimiter=';')
    w.writerow(CABECERAS)
    w.writerows(FILAS)

ruta_mal = os.path.join(carpeta, 'sin_cedula.csv')
with io.open(ruta_mal, 'w', encoding='utf-8', newline='') as f:
    csv.writer(f, delimiter=';').writerows([['Codigo', 'Nombre'], ['1', 'Juan']])


def correr(*args):
    r = subprocess.run([sys.executable, 'importar_socios.py', *args],
                       capture_output=True, text=True, env=os.environ,
                       encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '') + (r.stderr or '')


with app.app_context():
    db.create_all()

print("\n[1] Vista previa: no debe tocar la base")
codigo, salida = correr(ruta_csv)
check('corre sin error', codigo == 0)
check('avisa que no modifico nada', 'No se modifico nada' in salida)
with app.app_context():
    check('la base sigue vacia', Socio.query.count() == 0)

print("\n[2] Detecta las filas con problemas")
for motivo in ('sin cedula', 'cedula muy corta', 'cedula repetida en el archivo',
               'sin nombre ni apellido', 'N de socio repetido en el archivo'):
    check(f"detecta '{motivo}'", motivo in salida)

print("\n[3] Importa solo las filas validas")
codigo, salida = correr(ruta_csv, '--importar')
check('corre sin error', codigo == 0)
with app.app_context():
    total = Socio.query.count()
    check('importa las 4 filas validas', total == 4, f"(importo {total})")
    g = Socio.query.filter_by(dni='2500812').first()
    check('limpia los puntos de la cedula', g is not None,
          '(2.500.812 -> 2500812)')
    check('lee el CSV en cp1252 con ;', g and g.apellido == 'Villalba')
    check('acepta socio sin N de socio',
          Socio.query.filter_by(dni='3874512').first().numero_socio is None)

print("\n[4] Reimportar no duplica")
correr(ruta_csv, '--importar')
with app.app_context():
    check('sigue habiendo 4 socios', Socio.query.count() == 4,
          f"({Socio.query.count()})")

print("\n[5] --actualizar refresca los existentes")
FILAS[0][4] = '0999888777'
with io.open(ruta_csv, 'w', encoding='cp1252', newline='') as f:
    w = csv.writer(f, delimiter=';')
    w.writerow(CABECERAS)
    w.writerows(FILAS)
correr(ruta_csv, '--importar')
with app.app_context():
    check('sin --actualizar NO pisa el dato',
          Socio.query.filter_by(dni='2500812').first().telefono == '0980670440')
correr(ruta_csv, '--importar', '--actualizar')
with app.app_context():
    check('con --actualizar SI lo refresca',
          Socio.query.filter_by(dni='2500812').first().telefono == '0999888777')
    check('y no creó socios de más', Socio.query.count() == 4)

print("\n[6] Archivo sin columna de cédula")
codigo, salida = correr(ruta_mal)
check('lo rechaza', codigo != 0)
check('explica qué nombres acepta', 'Nombres aceptados' in salida)

print("\n[7] Integridad final")
with app.app_context():
    dnis = [s.dni for s in Socio.query.all()]
    check('sin cédulas duplicadas', len(dnis) == len(set(dnis)))
    check('todas las cédulas son solo dígitos', all(d.isdigit() for d in dnis))
    nros = [s.numero_socio for s in Socio.query.all() if s.numero_socio]
    check('sin N° de socio duplicados', len(nros) == len(set(nros)))

print("\n" + "=" * 60)
if fallos:
    print(f"RESULTADO: {len(fallos)} fallo(s):")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("RESULTADO: el importador del padrón anda")
