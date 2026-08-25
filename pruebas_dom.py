"""Detecta JavaScript que busca elementos que no existen en el HTML.

Es la clase de bug que dejaba el kiosco bloqueado: getElementById('nombreSocio')
sobre un id que solo existia en la plantilla vieja. El navegador lanza
TypeError sobre null y la funcion muere sin dejar rastro visible.

    python pruebas_dom.py
"""
import glob
import os
import re
import sys

# ids que el JS crea dinamicamente o que llegan de otra plantilla
IGNORAR = {
    'ticketModal',
}


def revisar(ruta):
    with open(ruta, encoding='utf-8') as f:
        html = f.read()

    # ids declarados en el markup, e ids generados por JS dentro de innerHTML
    declarados = set(re.findall(r'\bid=["\']([\w-]+)["\']', html))
    declarados |= set(re.findall(r'\bid=["\']\$\{[^}]+\}["\']', html))

    buscados = re.findall(r'getElementById\(\s*["\']([\w-]+)["\']\s*\)', html)

    faltantes = []
    for elemento in sorted(set(buscados)):
        if elemento not in declarados and elemento not in IGNORAR:
            # cuantas veces se usa, para estimar el impacto
            veces = buscados.count(elemento)
            faltantes.append((elemento, veces))
    return faltantes


def main():
    plantillas = sorted(glob.glob(os.path.join('templates', '*.html')))
    if not plantillas:
        print("[ERROR] No se encontraron plantillas en templates/")
        return 1

    total = 0
    for ruta in plantillas:
        faltantes = revisar(ruta)
        nombre = os.path.basename(ruta)
        if faltantes:
            print(f"  FALLA {nombre}")
            for elemento, veces in faltantes:
                print(f"         getElementById('{elemento}') "
                      f"-> ese id no existe en el HTML ({veces} uso/s)")
            total += len(faltantes)
        else:
            print(f"  OK    {nombre}")

    print("\n" + "=" * 58)
    if total:
        print(f"{total} referencia(s) rota(s): el JS va a lanzar TypeError sobre null")
        return 1
    print("Ningun JavaScript apunta a elementos inexistentes")
    return 0


if __name__ == '__main__':
    sys.exit(main())
