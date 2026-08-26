"""Respaldo de la base de datos, con verificacion.

Un respaldo que nunca se abrio no es un respaldo: despues de copiar, este
script ABRE la copia, cuenta sus registros y los compara con el original. Si
la copia esta corrupta se entera hoy, no el dia que haga falta restaurarla.

    python respaldar.py                 # respalda y verifica
    python respaldar.py --listar        # muestra los respaldos existentes
    python respaldar.py --restaurar <archivo>
    python respaldar.py --programar     # tarea diaria de Windows a las 23:00

La carpeta destino se puede cambiar con TIKETERA_CARPETA_RESPALDOS.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
ORIGEN = os.path.join(BASE, 'instance', 'tickets.db')
DESTINO = os.environ.get(
    'TIKETERA_CARPETA_RESPALDOS',
    os.path.join(os.path.expanduser('~'), 'Respaldos', 'TIKETERA'))
DIAS_A_CONSERVAR = int(os.environ.get('TIKETERA_DIAS_RESPALDO', '30'))

TABLAS = ('tickets', 'socios', 'usuarios', 'departamentos', 'historial_ticket',
          'avisos', 'secuencias_ticket')


def _contar(ruta):
    """Cuenta los registros de cada tabla. Sirve para comparar copia y original."""
    conteos = {}
    con = sqlite3.connect(f'file:{ruta}?mode=ro', uri=True)
    try:
        for tabla in TABLAS:
            try:
                conteos[tabla] = con.execute(
                    f'SELECT COUNT(*) FROM {tabla}').fetchone()[0]
            except sqlite3.Error:
                conteos[tabla] = None      # la tabla puede no existir todavia
    finally:
        con.close()
    return conteos


def _nombre_libre():
    """Nombre de archivo que no exista todavia.

    No alcanza con poner la hora en el nombre: dos respaldos dentro del mismo
    segundo se pisarian en silencio, y ahi se pierde una copia sin que nadie
    se entere. Si el nombre esta ocupado se agrega un sufijo.
    """
    marca = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    copia = os.path.join(DESTINO, f'tickets_{marca}.db')
    intento = 2
    while os.path.exists(copia):
        copia = os.path.join(DESTINO, f'tickets_{marca}_{intento}.db')
        intento += 1
    return copia


def respaldar():
    if not os.path.exists(ORIGEN):
        print(f'[ERROR] No existe la base: {ORIGEN}')
        return 1

    os.makedirs(DESTINO, exist_ok=True)
    copia = _nombre_libre()

    # La API de backup de SQLite copia en caliente, de forma consistente,
    # aunque el sistema este atendiendo en ese momento.
    origen = sqlite3.connect(f'file:{ORIGEN}?mode=ro', uri=True)
    destino = sqlite3.connect(copia)
    try:
        origen.backup(destino)
    finally:
        destino.close()
        origen.close()

    kb = os.path.getsize(copia) / 1024
    print(f'[OK] Respaldo creado: {os.path.basename(copia)}  ({kb:.0f} KB)')

    # --- Verificacion ---
    print('\nVerificando la copia...')
    con = sqlite3.connect(f'file:{copia}?mode=ro', uri=True)
    try:
        integridad = con.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        con.close()

    if integridad != 'ok':
        print(f'[ERROR] La copia esta corrupta: {integridad}')
        os.remove(copia)
        print('        Se elimino la copia defectuosa.')
        return 1
    print('  integridad ................ ok')

    original, respaldo = _contar(ORIGEN), _contar(copia)
    diferencias = [t for t in TABLAS if original.get(t) != respaldo.get(t)]
    for tabla in TABLAS:
        if respaldo.get(tabla) is not None:
            marca_ok = 'ok' if tabla not in diferencias else 'NO COINCIDE'
            print(f'  {tabla:<20} {respaldo[tabla]:>7} registros  {marca_ok}')

    if diferencias:
        # Puede pasar si alguien emitio un turno justo durante la copia
        print(f'\n[AVISO] Difieren: {", ".join(diferencias)}')
        print('        Suele ser un turno emitido durante la copia. Si se repite'
              ' todos los dias, revisar.')

    limpiar_viejos()
    return 0


def limpiar_viejos():
    limite = datetime.now() - timedelta(days=DIAS_A_CONSERVAR)
    borrados = 0
    for nombre in os.listdir(DESTINO):
        if not (nombre.startswith('tickets_') and nombre.endswith('.db')):
            continue
        ruta = os.path.join(DESTINO, nombre)
        if datetime.fromtimestamp(os.path.getmtime(ruta)) < limite:
            os.remove(ruta)
            borrados += 1
    if borrados:
        print(f'\n[OK] {borrados} respaldo(s) de mas de {DIAS_A_CONSERVAR} dias eliminados')


def listar():
    if not os.path.isdir(DESTINO):
        print(f'No hay respaldos todavia en {DESTINO}')
        return 0
    copias = sorted((n for n in os.listdir(DESTINO)
                     if n.startswith('tickets_') and n.endswith('.db')),
                    reverse=True)
    if not copias:
        print(f'No hay respaldos en {DESTINO}')
        return 0

    print(f'Respaldos en {DESTINO}\n')
    total = 0
    for nombre in copias:
        ruta = os.path.join(DESTINO, nombre)
        tam = os.path.getsize(ruta)
        total += tam
        fecha = datetime.fromtimestamp(os.path.getmtime(ruta))
        conteos = _contar(ruta)
        print(f"  {nombre:<28} {tam/1024:>7.0f} KB  {fecha:%d/%m/%Y %H:%M}  "
              f"{conteos.get('tickets') or 0} turnos, {conteos.get('socios') or 0} socios")
    print(f'\n  {len(copias)} respaldos, {total/1024/1024:.1f} MB en total')
    return 0


def restaurar(archivo):
    ruta = archivo if os.path.isabs(archivo) else os.path.join(DESTINO, archivo)
    if not os.path.exists(ruta):
        print(f'[ERROR] No existe: {ruta}')
        return 1

    conteos = _contar(ruta)
    print(f'Se va a restaurar: {os.path.basename(ruta)}')
    print(f"  {conteos.get('tickets') or 0} turnos, {conteos.get('socios') or 0} socios, "
          f"{conteos.get('usuarios') or 0} usuarios")
    print('\nEsto REEMPLAZA la base actual. Detenga el sistema antes de continuar.')
    if input('Escriba SI para confirmar: ').strip() != 'SI':
        print('Cancelado.')
        return 1

    # La base que se reemplaza se guarda igual, por si el respaldo no era el correcto
    if os.path.exists(ORIGEN):
        previo = f"{ORIGEN}.antes_de_restaurar_{datetime.now():%Y%m%d_%H%M%S}"
        shutil.copy2(ORIGEN, previo)
        print(f'[OK] La base actual se guardo como {os.path.basename(previo)}')

    shutil.copy2(ruta, ORIGEN)
    print('[LISTO] Base restaurada. Arranque el sistema con: python iniciar.py')
    return 0


def programar():
    """Crea la tarea diaria de Windows."""
    python = sys.executable.replace('python.exe', 'pythonw.exe')
    if not os.path.exists(python):
        python = sys.executable
    script = os.path.join(BASE, 'respaldar.py')
    comando = f'"{python}" "{script}"'

    print('Para programar el respaldo diario a las 23:00, ejecute esto en una')
    print('consola de PowerShell ABIERTA COMO ADMINISTRADOR:\n')
    print(f'  schtasks /Create /SC DAILY /TN "TIKETERA Respaldo" /TR \'{comando}\' '
          f'/ST 23:00 /RL HIGHEST /F\n')
    print('Para comprobar que quedo creada:')
    print('  schtasks /Query /TN "TIKETERA Respaldo"\n')
    print('Para quitarla:')
    print('  schtasks /Delete /TN "TIKETERA Respaldo" /F')
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        return respaldar()
    if args[0] == '--listar':
        return listar()
    if args[0] == '--programar':
        return programar()
    if args[0] == '--restaurar':
        if len(args) < 2:
            print('[ERROR] Indique el archivo. Vea los disponibles con --listar')
            return 1
        return restaurar(args[1])
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main())
