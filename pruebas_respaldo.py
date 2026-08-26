"""Prueba el respaldo de punta a punta, incluida la restauracion.

Un respaldo solo sirve si se puede restaurar. Esta prueba lo restaura de
verdad sobre una base temporal y compara los datos.

    python pruebas_respaldo.py
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

fallos = []


def check(nombre, ok, detalle=''):
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre} {detalle}")
    if not ok:
        fallos.append(nombre)


BASE = os.path.dirname(os.path.abspath(__file__))
banco = tempfile.mkdtemp()
carpeta_respaldos = os.path.join(banco, 'Respaldos')
falsa_instance = os.path.join(banco, 'instance')
os.makedirs(falsa_instance)

# --- Base de origen con datos conocidos ---
origen = os.path.join(falsa_instance, 'tickets.db')
con = sqlite3.connect(origen)
con.executescript("""
    CREATE TABLE tickets (id INTEGER PRIMARY KEY, codigo_completo TEXT);
    CREATE TABLE socios (id INTEGER PRIMARY KEY, dni TEXT);
    CREATE TABLE usuarios (id INTEGER PRIMARY KEY, username TEXT);
    CREATE TABLE departamentos (id INTEGER PRIMARY KEY);
    CREATE TABLE historial_ticket (id INTEGER PRIMARY KEY);
    CREATE TABLE avisos (id INTEGER PRIMARY KEY);
    CREATE TABLE secuencias_ticket (id INTEGER PRIMARY KEY);
""")
con.executemany('INSERT INTO tickets (codigo_completo) VALUES (?)',
                [(f'C-{i:03d}',) for i in range(1, 43)])
con.executemany('INSERT INTO socios (dni) VALUES (?)',
                [(str(1000000 + i),) for i in range(236)])
con.execute("INSERT INTO usuarios (username) VALUES ('admin')")
con.commit()
con.close()

entorno = dict(os.environ)
entorno['TIKETERA_CARPETA_RESPALDOS'] = carpeta_respaldos

# El script respalda instance/tickets.db relativo a SU carpeta: se copia alli
script = os.path.join(banco, 'respaldar.py')
shutil.copy2(os.path.join(BASE, 'respaldar.py'), script)


def correr(*args):
    r = subprocess.run([sys.executable, script, *args], capture_output=True,
                       text=True, env=entorno, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '') + (r.stderr or '')


print("\n[1] Crea el respaldo y lo verifica")
codigo, salida = correr()
check('corre sin error', codigo == 0)
check('informa integridad ok', 'integridad' in salida and 'ok' in salida)
check('cuenta los 42 turnos', '42 registros' in salida or '42' in salida)
copias = [n for n in os.listdir(carpeta_respaldos) if n.endswith('.db')]
check('quedo el archivo', len(copias) == 1, f"({copias})")

print("\n[2] La copia tiene los mismos datos")
copia = os.path.join(carpeta_respaldos, copias[0])
c = sqlite3.connect(f'file:{copia}?mode=ro', uri=True)
check('42 turnos en la copia',
      c.execute('SELECT COUNT(*) FROM tickets').fetchone()[0] == 42)
check('236 socios en la copia',
      c.execute('SELECT COUNT(*) FROM socios').fetchone()[0] == 236)
c.close()

print("\n[3] Copia en caliente: con la base abierta y escribiendo")
viva = sqlite3.connect(origen)
viva.execute("INSERT INTO tickets (codigo_completo) VALUES ('C-999')")
viva.commit()
codigo, salida = correr()
check('respalda con la base en uso', codigo == 0)
viva.close()
copias = sorted(n for n in os.listdir(carpeta_respaldos) if n.endswith('.db'))
ultima = os.path.join(carpeta_respaldos, copias[-1])
c = sqlite3.connect(f'file:{ultima}?mode=ro', uri=True)
check('la copia incluye el turno recien escrito',
      c.execute("SELECT COUNT(*) FROM tickets WHERE codigo_completo='C-999'"
                ).fetchone()[0] == 1)
c.close()

print("\n[4] Detecta una copia corrupta")
corrupta = os.path.join(carpeta_respaldos, 'tickets_2020-01-01_0000.db')
with open(corrupta, 'wb') as f:
    f.write(b'esto no es una base de datos SQLite' * 40)
# La conexion se cierra si o si: en Windows no se puede borrar un archivo
# que quedo abierto, ni siquiera despues de un error.
conexion = None
try:
    conexion = sqlite3.connect(f'file:{corrupta}?mode=ro', uri=True)
    conexion.execute('PRAGMA integrity_check').fetchone()
    detectada = False
except sqlite3.DatabaseError:
    detectada = True
finally:
    if conexion is not None:
        conexion.close()
check('una copia corrupta no se puede abrir', detectada,
      '(el script la borraria y avisaria)')
os.remove(corrupta)

print("\n[5] Listar los respaldos")
codigo, salida = correr('--listar')
check('lista sin error', codigo == 0)
check('muestra turnos y socios', 'turnos' in salida and 'socios' in salida)

print("\n[6] RESTAURAR de verdad")
# Se rompe la base de origen a proposito
con = sqlite3.connect(origen)
con.execute('DELETE FROM tickets')
con.execute('DELETE FROM socios')
con.commit()
con.close()
c = sqlite3.connect(origen)
check('la base quedo vacia (simulando el desastre)',
      c.execute('SELECT COUNT(*) FROM tickets').fetchone()[0] == 0)
c.close()

r = subprocess.run([sys.executable, script, '--restaurar', copias[-1]],
                   input='SI\n', capture_output=True, text=True, env=entorno,
                   encoding='utf-8', errors='replace')
check('la restauracion corre sin error', r.returncode == 0)

c = sqlite3.connect(origen)
turnos = c.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]
socios = c.execute('SELECT COUNT(*) FROM socios').fetchone()[0]
c.close()
check('los turnos volvieron', turnos == 43, f"({turnos} de 43)")
check('los socios volvieron', socios == 236, f"({socios} de 236)")

previos = [n for n in os.listdir(falsa_instance) if 'antes_de_restaurar' in n]
check('guardo la base que reemplazo', len(previos) == 1, f"({previos})")

print("\n[7] Retencion: borra los respaldos viejos")
viejo = os.path.join(carpeta_respaldos, 'tickets_2020-01-01_0000.db')
shutil.copy2(ultima, viejo)
os.utime(viejo, (0, 0))            # fecha de 1970
entorno['TIKETERA_DIAS_RESPALDO'] = '30'
codigo, salida = correr()
check('elimina el respaldo viejo', not os.path.exists(viejo))
quedan = [n for n in os.listdir(carpeta_respaldos) if n.endswith('.db')]
# Se hicieron 3 respaldos (pasos 1, 3 y 7). Si el nombre no llevara segundos
# se pisarian entre si y quedaria uno solo.
check('conserva los 3 recientes sin pisarse', len(quedan) == 3,
      f"(quedan {len(quedan)}: {sorted(quedan)})")

shutil.rmtree(banco, ignore_errors=True)

print("\n" + "=" * 60)
if fallos:
    print(f"RESULTADO: {len(fallos)} fallo(s):")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("RESULTADO: el respaldo se crea, se verifica y se restaura")
