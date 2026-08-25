"""Migracion idempotente del esquema de la base de datos.

Se puede ejecutar tantas veces como haga falta: detecta lo que ya existe y solo
aplica lo que falta. Hace una copia de seguridad antes de tocar nada.

    python migrar_db.py                    # migra instance/tickets.db
    python migrar_db.py otra/base.db       # migra la base indicada
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta

from config import Config

DB_POR_DEFECTO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'instance', 'tickets.db')
DB_PATH = sys.argv[1] if len(sys.argv) > 1 else DB_POR_DEFECTO

# Columnas nuevas: (tabla, columna, definicion SQL)
COLUMNAS_NUEVAS = [
    ('tickets', 'fecha_finalizacion', 'DATETIME'),
    ('tickets', 'atendido_por_id', 'INTEGER REFERENCES usuarios(id)'),
    # Numero de socio: en el padron y copiado en cada ticket emitido
    ('socios', 'numero_socio', 'VARCHAR(20)'),
    ('tickets', 'numero_socio', 'VARCHAR(20)'),
    # Atencion preferencial (Ley 4934)
    ('tickets', 'prioridad', 'VARCHAR(30)'),
    # Aviso mostrado como franja fija en la TV
    ('avisos', 'banner', 'BOOLEAN NOT NULL DEFAULT 0'),
    # Pieza grafica del aviso (archivo dentro de static/avisos/)
    ('avisos', 'imagen', 'VARCHAR(120)'),
    # Digital signage: vigencia de la campaña y segundos en pantalla
    ('avisos', 'fecha_desde', 'DATE'),
    ('avisos', 'fecha_hasta', 'DATE'),
    ('avisos', 'duracion', 'INTEGER NOT NULL DEFAULT 12'),
]

TABLA_AVISOS = """
CREATE TABLE IF NOT EXISTS avisos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo VARCHAR(120) NOT NULL,
    texto TEXT,
    destacado VARCHAR(120),
    icono VARCHAR(20) DEFAULT '📢',
    color VARCHAR(20) DEFAULT '#16a34a',
    orden INTEGER NOT NULL DEFAULT 0,
    activo BOOLEAN NOT NULL DEFAULT 1,
    banner BOOLEAN NOT NULL DEFAULT 0,
    fecha_creacion DATETIME
)
"""

TABLA_SECUENCIAS = """
CREATE TABLE IF NOT EXISTS secuencias_ticket (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    departamento_id INTEGER NOT NULL REFERENCES departamentos(id),
    fecha DATE NOT NULL,
    ultimo_numero INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_secuencia_depto_fecha UNIQUE (departamento_id, fecha)
)
"""

INDICES = [
    "CREATE INDEX IF NOT EXISTS ix_tickets_estado ON tickets (estado)",
    "CREATE INDEX IF NOT EXISTS ix_tickets_fecha_creacion ON tickets (fecha_creacion)",
    # UNIQUE parcial: varios socios pueden no tener numero cargado (NULL),
    # pero un numero cargado no se puede repetir.
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_socios_numero_socio "
    "ON socios (numero_socio) WHERE numero_socio IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_tickets_prioridad ON tickets (prioridad)",
]


def columnas_de(cur, tabla):
    return {fila[1] for fila in cur.execute(f"PRAGMA table_info({tabla})")}


def hacer_backup():
    marca = datetime.now().strftime('%Y%m%d_%H%M%S')
    destino = f"{DB_PATH}.bak_{marca}"
    shutil.copy2(DB_PATH, destino)
    print(f"[BACKUP] Copia de seguridad: {os.path.basename(destino)}")
    return destino


def backfill_secuencias(cur):
    """Carga los contadores con el ultimo numero ya emitido por dia/departamento.

    Sin esto, el primer ticket despues de migrar volveria a empezar en 1 y
    duplicaria codigos de la jornada en curso.
    """
    ya_cargadas = cur.execute("SELECT COUNT(*) FROM secuencias_ticket").fetchone()[0]
    if ya_cargadas:
        print(f"[SKIP] secuencias_ticket ya tiene {ya_cargadas} registros")
        return

    offset = timedelta(hours=Config.TZ_OFFSET_HOURS)
    maximos = {}

    for dep_id, numero, fecha_creacion in cur.execute(
        "SELECT departamento_id, numero, fecha_creacion FROM tickets"
    ):
        if not fecha_creacion:
            continue
        texto = str(fecha_creacion).replace('T', ' ').split('.')[0]
        try:
            creado_utc = datetime.strptime(texto, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                creado_utc = datetime.strptime(texto[:10], '%Y-%m-%d')
            except ValueError:
                continue
        dia_local = (creado_utc + offset).date()
        clave = (dep_id, dia_local.isoformat())
        maximos[clave] = max(maximos.get(clave, 0), numero or 0)

    for (dep_id, dia), ultimo in maximos.items():
        cur.execute(
            "INSERT OR IGNORE INTO secuencias_ticket "
            "(departamento_id, fecha, ultimo_numero) VALUES (?, ?, ?)",
            (dep_id, dia, ultimo)
        )
    print(f"[OK] Contadores inicializados: {len(maximos)} combinaciones dia/departamento")


def vincular_operadores(cur):
    """Asocia los tickets historicos al usuario cuyo puesto los atendio."""
    filas = cur.execute(
        "SELECT id, puesto, nombre FROM usuarios"
    ).fetchall()
    total = 0
    for user_id, puesto, nombre in filas:
        for etiqueta in filter(None, (puesto, nombre)):
            cur.execute(
                "UPDATE tickets SET atendido_por_id = ? "
                "WHERE atendido_por_id IS NULL AND puesto_atencion = ?",
                (user_id, etiqueta)
            )
            total += cur.rowcount
    if total:
        print(f"[OK] {total} tickets historicos vinculados a su operador")


def migrar():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] No existe la base de datos en {DB_PATH}")
        print("        Ejecute primero: python init_db.py")
        return False

    hacer_backup()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    try:
        for tabla, columna, definicion in COLUMNAS_NUEVAS:
            if columna in columnas_de(cur, tabla):
                print(f"[SKIP] {tabla}.{columna} ya existe")
            else:
                cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
                print(f"[OK] Columna agregada: {tabla}.{columna}")

        cur.execute(TABLA_SECUENCIAS)
        print("[OK] Tabla secuencias_ticket lista")

        cur.execute(TABLA_AVISOS)
        print("[OK] Tabla avisos lista")

        for sql in INDICES:
            cur.execute(sql)
        print("[OK] Indices verificados")

        backfill_secuencias(cur)
        vincular_operadores(cur)

        # Los tickets viejos en estado 'Llamado' quedan cerrados: no tiene
        # sentido arrastrar llamadas de jornadas anteriores a la TV.
        cur.execute(
            "UPDATE tickets SET estado = 'Finalizado', "
            "fecha_finalizacion = COALESCE(fecha_finalizacion, fecha_atencion) "
            "WHERE estado IN ('Llamado', 'En atención')"
        )
        if cur.rowcount:
            print(f"[OK] {cur.rowcount} tickets colgados en 'Llamado' fueron cerrados")

        conn.commit()
        print("\n[LISTO] Migracion completada.")
        return True
    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] La migracion fallo y se revirtio: {e}")
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    migrar()
