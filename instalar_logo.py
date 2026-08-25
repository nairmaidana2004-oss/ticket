"""Instala el logo institucional en el sistema.

Guarde la imagen del logo donde quiera (por ejemplo en Descargas) y pase la
ruta. El script la valida, la copia a static/ con el nombre correcto y a partir
de ahi aparece sola en el kiosco, la TV, el login, el panel de administracion,
el ticket en pantalla y el ticket impreso.

    python instalar_logo.py "C:\\Users\\Usuario\\Downloads\\logo.png"

Para volver al logo de respaldo:

    python instalar_logo.py --quitar
"""
import os
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, 'static')

# El sistema prefiere estos formatos, en este orden (ver inyectar_logo en app.py)
EXTENSIONES = {'.png': 'logo-cooperativa.png',
               '.jpg': 'logo-cooperativa.jpg',
               '.jpeg': 'logo-cooperativa.jpeg'}

# Firmas de archivo, para no copiar algo que no sea una imagen
FIRMAS = {
    b'\x89PNG\r\n\x1a\n': '.png',
    b'\xff\xd8\xff': '.jpg',
}

TAMANO_MAXIMO = 4 * 1024 * 1024  # 4 MB: mas que suficiente para un logo


def _formato_real(ruta):
    """Detecta el formato leyendo el archivo, no confiando en la extension."""
    with open(ruta, 'rb') as f:
        cabecera = f.read(8)
    for firma, ext in FIRMAS.items():
        if cabecera.startswith(firma):
            return ext
    return None


def quitar():
    quitados = []
    for nombre in EXTENSIONES.values():
        destino = os.path.join(STATIC, nombre)
        if os.path.exists(destino):
            os.remove(destino)
            quitados.append(nombre)
    if quitados:
        print("[OK] Quitado: " + ", ".join(quitados))
        print("     El sistema vuelve al logo de respaldo (logo-cooperativa.svg)")
    else:
        print("[INFO] No habia ningun logo instalado; ya se usa el de respaldo")
    return 0


def instalar(origen):
    if not os.path.exists(origen):
        print(f"[ERROR] No existe el archivo: {origen}")
        return 1

    if os.path.getsize(origen) == 0:
        print("[ERROR] El archivo esta vacio")
        return 1

    if os.path.getsize(origen) > TAMANO_MAXIMO:
        mb = os.path.getsize(origen) / 1024 / 1024
        print(f"[ERROR] El archivo pesa {mb:.1f} MB. Use una imagen de menos de 4 MB.")
        return 1

    formato = _formato_real(origen)
    if not formato:
        print("[ERROR] El archivo no es un PNG ni un JPG.")
        print("        Abralo en Paint y use 'Guardar como' -> PNG.")
        return 1

    if formato == '.png':
        destino_nombre = EXTENSIONES['.png']
    else:
        destino_nombre = EXTENSIONES['.jpg']

    os.makedirs(STATIC, exist_ok=True)

    # Si ya habia otro formato instalado, se quita para que no gane el equivocado
    for nombre in EXTENSIONES.values():
        anterior = os.path.join(STATIC, nombre)
        if nombre != destino_nombre and os.path.exists(anterior):
            os.remove(anterior)
            print(f"[INFO] Se quito el logo anterior ({nombre})")

    destino = os.path.join(STATIC, destino_nombre)
    shutil.copy2(origen, destino)

    kb = os.path.getsize(destino) / 1024
    print(f"[OK] Logo instalado: static/{destino_nombre} ({kb:.0f} KB)")
    print("")
    print("Ya aparece en:")
    for pantalla in ('kiosco (pantalla de entrada)', 'sala de espera (TV)',
                     'pantalla de login', 'panel de administracion',
                     'ticket en pantalla', 'ticket impreso'):
        print(f"   - {pantalla}")
    print("")
    print("Si el sistema esta corriendo, reinicielo y refresque con Ctrl+F5.")
    if formato != '.png':
        print("")
        print("Sugerencia: un PNG con fondo transparente se ve mejor que un JPG,")
        print("            que siempre trae un recuadro de fondo.")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    if sys.argv[1] in ('--quitar', '--remove', '-q'):
        return quitar()
    return instalar(sys.argv[1].strip('"').strip())


if __name__ == '__main__':
    sys.exit(main())
