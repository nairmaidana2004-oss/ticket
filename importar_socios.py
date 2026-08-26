"""Importa el padron de socios desde un Excel o un CSV.

Reconoce solo las columnas por su nombre, sin importar el orden ni las
mayusculas, asi que sirve para el archivo que exporte el sistema central sin
tener que prepararlo a mano.

    python importar_socios.py padron.xlsx              # muestra que haria
    python importar_socios.py padron.xlsx --importar   # lo aplica
    python importar_socios.py padron.csv --importar --actualizar

Sin --importar no toca la base: solo muestra la vista previa y los problemas.
Con --actualizar, a los socios que ya existen les refresca los datos; sin esa
opcion se los saltea.
"""
import csv
import io
import os
import sys

from app import app
from models import Socio, db

# Nombres aceptados para cada campo. Se compara en minusculas y sin espacios.
COLUMNAS = {
    'numero_socio': ('numero_socio', 'numerosocio', 'nrosocio', 'nro_socio',
                     'nro', 'socio', 'nsocio', 'n_socio', 'numero de socio',
                     'codigo', 'cod_socio'),
    'dni': ('dni', 'cedula', 'ci', 'documento', 'nro_documento', 'cedula_identidad',
            'nro_ci', 'doc', 'cin'),
    'nombre': ('nombre', 'nombres', 'primer_nombre'),
    'apellido': ('apellido', 'apellidos'),
    'telefono': ('telefono', 'tel', 'celular', 'movil', 'contacto'),
    'email': ('email', 'correo', 'mail', 'correo_electronico'),
}


def _normalizar(cabecera):
    return str(cabecera or '').strip().lower().replace(' ', '_').replace('.', '')


def mapear_columnas(cabeceras):
    """Devuelve {campo: indice} segun los nombres de la primera fila."""
    mapa = {}
    for indice, bruto in enumerate(cabeceras):
        limpio = _normalizar(bruto)
        for campo, alias in COLUMNAS.items():
            if campo in mapa:
                continue
            if limpio in alias:
                mapa[campo] = indice
    return mapa


def leer_excel(ruta):
    import openpyxl
    libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    hoja = libro.active
    filas = []
    for fila in hoja.iter_rows(values_only=True):
        # Se descartan las filas totalmente vacias que Excel suele dejar al final
        if fila and any(c is not None and str(c).strip() for c in fila):
            filas.append(['' if c is None else str(c).strip() for c in fila])
    libro.close()
    return filas


def leer_csv(ruta):
    # Excel en español guarda con ; y en cp1252; se prueban las combinaciones
    for codificacion in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            with io.open(ruta, encoding=codificacion, newline='') as f:
                muestra = f.read(4096)
                f.seek(0)
                try:
                    dialecto = csv.Sniffer().sniff(muestra, delimiters=';,\t|')
                except csv.Error:
                    dialecto = csv.excel
                    dialecto.delimiter = ';' if muestra.count(';') > muestra.count(',') else ','
                return [[(c or '').strip() for c in fila]
                        for fila in csv.reader(f, dialecto)
                        if any((c or '').strip() for c in fila)]
        except UnicodeDecodeError:
            continue
    raise SystemExit('[ERROR] No se pudo leer el CSV: codificacion desconocida')


def solo_digitos(valor):
    """Deja la cedula en digitos: quita puntos, guiones y espacios."""
    return ''.join(c for c in str(valor) if c.isdigit())


def analizar(ruta):
    extension = os.path.splitext(ruta)[1].lower()
    if extension in ('.xlsx', '.xlsm'):
        filas = leer_excel(ruta)
    elif extension in ('.csv', '.txt'):
        filas = leer_csv(ruta)
    elif extension == '.xls':
        raise SystemExit('[ERROR] El formato .xls es viejo. Abralo en Excel y '
                         'guardelo como .xlsx o .csv')
    else:
        raise SystemExit(f'[ERROR] Formato no soportado: {extension}')

    if not filas:
        raise SystemExit('[ERROR] El archivo esta vacio')

    mapa = mapear_columnas(filas[0])
    if 'dni' not in mapa:
        print('[ERROR] No se encontro la columna de cedula.')
        print(f'        Cabeceras leidas: {filas[0]}')
        print(f'        Nombres aceptados: {", ".join(COLUMNAS["dni"])}')
        raise SystemExit(1)

    return filas[0], filas[1:], mapa


def procesar(ruta, aplicar=False, actualizar=False):
    cabeceras, filas, mapa = analizar(ruta)

    print(f"Archivo: {os.path.basename(ruta)}  ({len(filas)} filas de datos)\n")
    print("Columnas reconocidas:")
    for campo in COLUMNAS:
        if campo in mapa:
            print(f"  {cabeceras[mapa[campo]]:<28} ->  {campo}")
    faltantes = [c for c in ('numero_socio', 'nombre', 'apellido') if c not in mapa]
    if faltantes:
        print(f"  (sin columna para: {', '.join(faltantes)})")

    def valor(fila, campo):
        i = mapa.get(campo)
        return fila[i].strip() if i is not None and i < len(fila) else ''

    listos, problemas = [], []
    vistos_dni, vistos_nro = set(), set()

    for numero_fila, fila in enumerate(filas, start=2):
        dni = solo_digitos(valor(fila, 'dni'))
        nombre = valor(fila, 'nombre')
        apellido = valor(fila, 'apellido')
        nro = valor(fila, 'numero_socio')

        if not dni:
            problemas.append((numero_fila, 'sin cedula', valor(fila, 'dni')))
            continue
        if len(dni) < 5:
            problemas.append((numero_fila, 'cedula muy corta', dni))
            continue
        if dni in vistos_dni:
            problemas.append((numero_fila, 'cedula repetida en el archivo', dni))
            continue
        if not nombre and not apellido:
            problemas.append((numero_fila, 'sin nombre ni apellido', dni))
            continue
        if nro and nro in vistos_nro:
            problemas.append((numero_fila, 'N de socio repetido en el archivo', nro))
            continue

        vistos_dni.add(dni)
        if nro:
            vistos_nro.add(nro)
        listos.append({
            'numero_socio': nro or None, 'dni': dni,
            'nombre': nombre or apellido, 'apellido': apellido or '',
            'telefono': valor(fila, 'telefono') or None,
            'email': valor(fila, 'email') or None,
        })

    print(f"\nVISTA PREVIA (primeros 5 de {len(listos)}):")
    for s in listos[:5]:
        print(f"  {(s['numero_socio'] or '-'):>8}  {s['dni']:>10}  "
              f"{s['apellido']}, {s['nombre']}")

    if problemas:
        print(f"\nFILAS CON PROBLEMAS ({len(problemas)}):")
        for numero_fila, motivo, dato in problemas[:15]:
            print(f"  fila {numero_fila:<6} {motivo:<32} {dato}")
        if len(problemas) > 15:
            print(f"  ... y {len(problemas) - 15} mas")

    with app.app_context():
        existentes_dni = {s.dni: s for s in Socio.query.all()}
        nuevos = [s for s in listos if s['dni'] not in existentes_dni]
        repetidos = [s for s in listos if s['dni'] in existentes_dni]

        print(f"\nRESUMEN")
        print(f"  {len(nuevos):>6}  socios nuevos")
        print(f"  {len(repetidos):>6}  ya estaban en el padron"
              f"{'  (se actualizan)' if actualizar else '  (se saltean)'}")
        print(f"  {len(problemas):>6}  filas con problemas (no se importan)")

        if not aplicar:
            print("\n[VISTA PREVIA] No se modifico nada.")
            print("               Agregue --importar para aplicarlo.")
            return 0

        # Los numeros de socio ya usados por OTRA cedula no se pueden duplicar
        nros_ocupados = {s.numero_socio: s.dni for s in existentes_dni.values()
                         if s.numero_socio}

        creados = actualizados = sin_numero = 0
        for datos in listos:
            existente = existentes_dni.get(datos['dni'])

            nro = datos['numero_socio']
            if nro and nros_ocupados.get(nro) not in (None, datos['dni']):
                nro = None            # ese numero ya es de otro socio
                sin_numero += 1

            if existente:
                if not actualizar:
                    continue
                existente.nombre = datos['nombre']
                existente.apellido = datos['apellido']
                if nro:
                    existente.numero_socio = nro
                if datos['telefono']:
                    existente.telefono = datos['telefono']
                if datos['email']:
                    existente.email = datos['email']
                existente.activo = True
                actualizados += 1
            else:
                db.session.add(Socio(
                    numero_socio=nro, dni=datos['dni'], nombre=datos['nombre'],
                    apellido=datos['apellido'], telefono=datos['telefono'],
                    email=datos['email'], activo=True))
                if nro:
                    nros_ocupados[nro] = datos['dni']
                creados += 1

        db.session.commit()

        print(f"\n[LISTO]")
        print(f"  {creados:>6}  socios creados")
        print(f"  {actualizados:>6}  socios actualizados")
        if sin_numero:
            print(f"  {sin_numero:>6}  quedaron sin N de socio (ya lo tenia otra cedula)")
        print(f"\n  Total en el padron: {Socio.query.count()}")
    return 0


def main():
    argumentos = [a for a in sys.argv[1:] if not a.startswith('--')]
    opciones = {a for a in sys.argv[1:] if a.startswith('--')}

    if not argumentos:
        print(__doc__)
        return 1
    ruta = argumentos[0]
    if not os.path.exists(ruta):
        print(f'[ERROR] No existe el archivo: {ruta}')
        return 1

    return procesar(ruta, aplicar='--importar' in opciones,
                    actualizar='--actualizar' in opciones)


if __name__ == '__main__':
    sys.exit(main())
