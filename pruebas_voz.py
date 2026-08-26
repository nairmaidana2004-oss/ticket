import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, r"c:\Users\Usuario\OneDrive - COOPERATIVA REDUCTO LIMITADA\Escritorio\TIKETERA")
import cdp_cliente

fallos = []


def check(nombre, ok, detalle=''):
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre} {detalle}")
    if not ok:
        fallos.append(nombre)


p = cdp_cliente.abrir('http://localhost:5001/sala_espera')
time.sleep(4)
p.comando('Emulation.setDeviceMetricsOverride', width=1920, height=1080,
          deviceScaleFactor=1, mobile=False)
time.sleep(1.5)

print("\n[1] Como se pronuncia el codigo del turno")
for codigo, esperado in (('C-005', 'C, 5'), ('AH-012', 'A H, 12'),
                         ('A-001', 'A, 1'), ('T-100', 'T, 100')):
    real = p.js(f"codigoHablado('{codigo}')")
    check(f"{codigo:<8} -> '{real}'", real == esperado, f"(esperado '{esperado}')")

print("\n[2] Texto completo del anuncio")
casos = [
    ({'codigo_completo': 'C-005', 'puesto_atencion': 'Ventanilla 1',
      'departamento': {'nombre': 'Créditos'}, 'prioridad_texto': None},
     'Turno C, 5. Diríjase a Ventanilla 1.'),
    ({'codigo_completo': 'AH-012', 'puesto_atencion': 'Ventanilla 2',
      'departamento': {'nombre': 'Ahorros'}, 'prioridad_texto': 'Adulto mayor'},
     'Atención preferencial. Turno A H, 12. Diríjase a Ventanilla 2.'),
    ({'codigo_completo': 'A-003', 'puesto_atencion': None,
      'departamento': {'nombre': 'Atención al Socio'}, 'prioridad_texto': None},
     'Turno A, 3. Diríjase a Atención al Socio.'),
]
import json
for ticket, esperado in casos:
    real = p.js(f"textoDelAnuncio({json.dumps(ticket)})")
    check(f'"{real}"', real == esperado, f"(esperado: {esperado})")

print("\n[3] Voz elegida")
voz = p.js("vozElegida ? vozElegida.name + ' [' + vozElegida.lang + ']' : '(ninguna)'")
print(f"      {voz}")
check('eligio una voz en español', 'es-' in (voz or '').lower() or 'Spanish' in (voz or ''))

print("\n[4] Audio bloqueado al abrir (sin tocar la pantalla)")
bloqueado = p.js("audioBloqueado()")
check('detecta que esta bloqueado', bloqueado is True)
visible = p.js("document.getElementById('activarSonido').classList.contains('visible')")
check('muestra el aviso para activarlo', visible is True)
check('el indicador esta en mudo',
      p.js("document.getElementById('indicadorSonido').textContent") == '🔇')
p.captura(os.path.join(AQUI, 'capturas', 'v_activar.png'))

print("\n[5] Al tocar la pantalla se desbloquea")
# Un .click() desde JavaScript NO cuenta como gesto del usuario: el navegador
# solo desbloquea el audio con un evento de entrada real. Se envia uno de
# verdad por el protocolo, como si alguien tocara la pantalla.
for tipo in ('mousePressed', 'mouseReleased'):
    p.comando('Input.dispatchMouseEvent', type=tipo, x=960, y=540,
              button='left', clickCount=1)
time.sleep(2.5)
check('el audio queda activo', p.js("audioBloqueado()") is False,
      f"(estado: {p.js('contextoAudio ? contextoAudio.state : None')})")
check('el aviso desaparece',
      p.js("document.getElementById('activarSonido').classList.contains('visible')") is False)
check('el indicador vuelve a sonido',
      p.js("document.getElementById('indicadorSonido').textContent") == '🔊')

print("\n[6] Anuncia de verdad")
p.js("speechSynthesis.cancel(); true;")
time.sleep(0.5)
p.js("""
  window.__dichos = [];
  const original = speechSynthesis.speak.bind(speechSynthesis);
  speechSynthesis.speak = function(u) { window.__dichos.push(u.text); original(u); };
  speakTicket({codigo_completo: 'C-007', puesto_atencion: 'Ventanilla 1',
               departamento: {nombre: 'Créditos'}, prioridad_texto: null});
  true;
""")
time.sleep(1)
dichos = p.js("window.__dichos")
print(f"      locuciones encoladas: {dichos}")
check('anuncia dos veces', len(dichos or []) == 2)
check('dice el turno y el puesto',
      dichos and 'Turno C, 7' in dichos[0] and 'Ventanilla 1' in dichos[0])

p.cerrar()

print("\n" + "=" * 60)
if fallos:
    print(f"RESULTADO: {len(fallos)} fallo(s):")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("RESULTADO: el anuncio por voz anda")
