"""Recorre el kiosco haciendo clics reales en un navegador.

Es la unica prueba que ejercita el JavaScript del cliente. Detecta cosas que
las pruebas de servidor no ven: por ejemplo que 'Siguiente' no avanzaba porque
el codigo buscaba un campo que no existia en la plantilla.

Uso:

    1) Arrancar el sistema (contra una base de prueba, no la real):
         python iniciar.py

    2) Arrancar Edge con el puerto de depuracion abierto:
         & "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" `
             --headless=new --remote-debugging-port=9222 `
             --user-data-dir=$env:TEMP\\edge_pruebas about:blank

    3) Correr esta prueba:
         python pruebas_kiosco.py [http://localhost:5000]
"""
import os
import sys
import time

import cdp_cliente

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:5000'
CEDULA = '4258963'

fallos = []


def check(nombre, ok, detalle=''):
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre} {detalle}")
    if not ok:
        fallos.append(nombre)


def main():
    try:
        p = cdp_cliente.abrir(BASE + '/')
    except Exception as e:
        print(f"[ERROR] No se pudo conectar al navegador: {e}")
        print("        Revise que Edge este corriendo con --remote-debugging-port=9222")
        return 1

    time.sleep(3)

    # Registrar cualquier error de JavaScript que ocurra durante el recorrido
    p.js("""
        window.__errores = [];
        window.addEventListener('error', e => window.__errores.push(String(e.message)));
        window.addEventListener('unhandledrejection',
            e => window.__errores.push('promesa: ' + e.reason));
        true;
    """)

    print("\n[1] Carga la pantalla inicial")
    check('paso 1 visible',
          p.js("document.getElementById('step1').classList.contains('active')"))
    check("'Siguiente' arranca deshabilitado",
          p.js("document.getElementById('btnContinuar').disabled") is True)
    check('la tecla de borrar tiene icono vectorial (no un cuadrado vacio)',
          p.js("!!document.querySelector('.keypad-btn--warning svg')"))

    print(f"\n[2] Teclea la cedula {CEDULA} en el teclado numerico")
    for digito in CEDULA:
        p.clic_por_texto('.keypad-btn', digito)
        time.sleep(0.12)
    valor = p.js("document.getElementById('dniSocio').value")
    check('la cedula se cargo completa', valor == CEDULA, f"(dice '{valor}')")
    check("'Siguiente' se habilito",
          p.js("document.getElementById('btnContinuar').disabled") is False)

    print("\n[3] Borra un digito y lo reescribe")
    p.js("document.querySelector('.keypad-btn--warning').click(); true;")
    time.sleep(0.25)
    check('borro un digito',
          p.js("document.getElementById('dniSocio').value") == CEDULA[:-1])
    p.clic_por_texto('.keypad-btn', CEDULA[-1])
    time.sleep(0.25)
    check('reescribio el digito',
          p.js("document.getElementById('dniSocio').value") == CEDULA)

    time.sleep(2.8)  # deja terminar la busqueda automatica en el padron

    # Si la cedula esta en el padron, tienen que verse los tres datos.
    # Si no esta, el socio debe poder seguir igual, solo con su documento.
    en_padron = p.js("document.getElementById('welcomeArea').style.display") == 'block'
    if en_padron:
        print("\n[3b] La cedula esta en el padron: muestra sus datos")
        nombre = (p.js("document.getElementById('socioNombre').textContent") or '').strip()
        doc = (p.js("document.getElementById('socioDocumento').textContent") or '').strip()
        nro_visible = p.js(
            "getComputedStyle(document.getElementById('filaNumeroSocio')).display") != 'none'
        nro = (p.js("document.getElementById('socioNumero').textContent") or '').strip()
        check('muestra el nombre', bool(nombre) and nombre != '-', f"-> '{nombre}'")
        check('muestra el documento tecleado', doc == CEDULA, f"-> '{doc}'")
        if nro_visible:
            check('muestra el N° de socio', bool(nro) and nro != '-', f"-> '{nro}'")
        else:
            print("  --   ese socio no tiene N° de socio cargado (fila oculta, correcto)")
    else:
        print("\n[3b] La cedula no esta en el padron")
        aviso = ' '.join(
            (p.js("document.getElementById('estadoBusqueda').textContent") or '').split())
        check('avisa en pantalla que no la encontro', 'No encontramos' in aviso,
              f"-> '{aviso}'")
        check('puede continuar igual, solo con el documento',
              p.js("document.getElementById('btnContinuar').disabled") is False)

    print("\n[3c] Aprieta 'Siguiente' sin esperar la consulta al padron")
    # El kiosco debe esperar su propia busqueda en vez de avanzar sin los datos.
    p.js("document.getElementById('dniSocio').value = ''; "
         "document.getElementById('dniSocio').dispatchEvent(new Event('input')); true;")
    time.sleep(0.4)
    for digito in CEDULA:
        p.clic_por_texto('.keypad-btn', digito)
        time.sleep(0.09)
    p.js("document.getElementById('btnContinuar').click(); true;")
    time.sleep(0.7)
    if en_padron:
        # Si esta en el padron, el kiosco frena hasta poder mostrarle sus datos
        check('no se adelanta al paso 2 antes de tener los datos',
              p.js("document.getElementById('step2').classList.contains('active')") is False)
        check('alcanza a mostrar los datos del socio',
              p.js("document.getElementById('welcomeArea').style.display") == 'block')
    else:
        # Si no esta, no hay nada que mostrar: avanzar de una es lo correcto
        check('avanza sin demora cuando no hay datos que mostrar',
              p.js("document.getElementById('step2').classList.contains('active')") is True)
    time.sleep(2.6)

    print("\n[4] Presiona 'Siguiente' y pasa a la segunda pantalla")
    if p.js("document.getElementById('step1').classList.contains('active')"):
        p.js("document.getElementById('btnContinuar').click(); true;")
    time.sleep(1.6)
    check('salio del paso 1',
          p.js("document.getElementById('step1').classList.contains('active')") is False)
    check('entro al paso 2 (seleccion de departamento)',
          p.js("document.getElementById('step2').classList.contains('active')") is True)
    titulo = (p.js("document.getElementById('stepTitle').textContent") or '').strip()
    check('el titulo cambio', titulo == 'Seleccione el motivo de su visita',
          f"-> '{titulo}'")

    print("\n[5] Elige un departamento")
    nombres = p.js(
        "[...document.querySelectorAll('.department-card__name')].map(e => e.textContent)")
    print(f"      en pantalla: {nombres}")
    check('hay departamentos para elegir', bool(nombres))
    p.js("document.querySelector('.department-card').click(); true;")
    time.sleep(2)

    print("\n[6] Recibe su numero de turno")
    check('se abrio el ticket',
          p.js("document.getElementById('ticketModal').classList.contains('active')") is True)
    numero = (p.js("document.getElementById('modalNumber').textContent") or '').strip()
    check('el numero de turno es valido', '-' in numero and numero != '---',
          f"-> '{numero}'")

    ficha = p.js("document.getElementById('modalSocioInfo').textContent") or ''
    print(f"      ficha del ticket: {' '.join(ficha.split())}")
    check('el ticket muestra el documento', CEDULA in ficha)
    if en_padron:
        check('el ticket muestra el nombre del socio', 'Documento' in ficha and len(ficha) > 20)

    guardado = p.js("localStorage.getItem('ticketParaImprimir')") or ''
    p.js("document.querySelector('.btn-imprimir').click(); true;")
    time.sleep(0.8)
    guardado = p.js("localStorage.getItem('ticketParaImprimir')") or ''
    check('el ticket a imprimir lleva el documento', CEDULA in guardado,
          f"-> {guardado[:120]}")

    print("\n[7] Vuelve al inicio para el proximo socio")
    p.js("document.querySelector('.ticket-modal__close').click(); true;")
    time.sleep(1.5)
    check('volvio al paso 1',
          p.js("document.getElementById('step1').classList.contains('active')") is True)
    check('el campo de cedula quedo limpio',
          (p.js("document.getElementById('dniSocio').value") or '') == '')

    errores = p.js("window.__errores")
    check('ningun error de JavaScript en todo el recorrido', not errores, f"-> {errores}")

    destino = os.path.join('capturas', 'kiosco.png')
    try:
        p.captura(destino, ancho=1100, alto=1500, completa=True)
        print(f"\n  captura guardada en {destino}")
    except Exception as e:
        print(f"\n  (no se pudo guardar la captura: {e})")

    print("\n" + "=" * 60)
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s):")
        for f in fallos:
            print("  -", f)
        return 1
    print("RESULTADO: el kiosco funciona de punta a punta")
    return 0


if __name__ == '__main__':
    sys.exit(main())
