"""Verifica el comportamiento de digital signage: vigencia y duracion."""
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

BASE = 'http://localhost:5001'
fallos = []


def check(nombre, ok, detalle=''):
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre} {detalle}")
    if not ok:
        fallos.append(nombre)


cj = http.cookiejar.CookieJar()
anon = urllib.request.build_opener()
adm = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
adm.open(urllib.request.Request(
    BASE + '/login',
    data=urllib.parse.urlencode({'username': 'admin', 'password': 'admin123'}).encode()))


def api(op, ruta, metodo='GET', datos=None):
    cuerpo = json.dumps(datos).encode('utf-8') if datos is not None else None
    headers = {'Content-Type': 'application/json'} if datos is not None else {}
    req = urllib.request.Request(BASE + ruta, data=cuerpo, headers=headers, method=metodo)
    try:
        with op.open(req) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')[:120]


hoy = date.today()
ayer = (hoy - timedelta(days=1)).isoformat()
manana = (hoy + timedelta(days=1)).isoformat()

print("\n[1] Una campaña VENCIDA no sale en la TV")
c, aviso = api(adm, '/api/avisos', 'POST', {
    'titulo': 'ZZZ prueba vencida', 'icono': '🧪', 'color': '#dc2626',
    'fecha_hasta': ayer, 'duracion': 9})
check('se creó', c == 201)
check('el panel la marca vencida', aviso['estado_vigencia'] == 'vencido',
      f"(dice {aviso['estado_vigencia']})")
_, tv = api(anon, '/api/avisos')
check('la TV NO la recibe',
      not any(a['id'] == aviso['id'] for a in tv))

print("\n[2] Una campaña PROGRAMADA todavía no sale")
c, prog = api(adm, '/api/avisos', 'POST', {
    'titulo': 'ZZZ prueba futura', 'icono': '🧪', 'color': '#38bdf8',
    'fecha_desde': manana})
check('el panel la marca programada', prog['estado_vigencia'] == 'programado',
      f"(dice {prog['estado_vigencia']})")
_, tv = api(anon, '/api/avisos')
check('la TV NO la recibe todavía',
      not any(a['id'] == prog['id'] for a in tv))

print("\n[3] Al entrar en vigencia, aparece sola")
api(adm, f"/api/avisos/{prog['id']}", 'PUT', {'fecha_desde': hoy.isoformat()})
_, tv = api(anon, '/api/avisos')
check('ahora SÍ la recibe',
      any(a['id'] == prog['id'] for a in tv))

print("\n[4] Duración por pieza")
_, tv = api(anon, '/api/avisos')
duraciones = {a['titulo']: a['duracion'] for a in tv}
check('el flyer largo dura 18 s', duraciones.get('Asociate hoy') == 18,
      f"({duraciones.get('Asociate hoy')})")
check('la pieza de tarjetas dura 15 s', duraciones.get('Recargá tus tarjetas') == 15,
      f"({duraciones.get('Recargá tus tarjetas')})")
check('un titular simple dura 12 s',
      duraciones.get('Crédito para tu negocio') == 12)

print("\n[5] Validaciones")
c, r = api(adm, '/api/avisos', 'POST', {'titulo': 'ZZZ rango invertido',
                                        'fecha_desde': manana, 'fecha_hasta': ayer})
check('rechaza desde > hasta', c == 400, f"(dio {c})")
c, r = api(adm, '/api/avisos', 'POST', {'titulo': 'ZZZ fecha basura',
                                        'fecha_desde': '30-12-2026'})
check('rechaza formato de fecha inválido', c == 400, f"(dio {c})")
c, r = api(adm, '/api/avisos', 'POST', {'titulo': 'ZZZ duracion enorme',
                                        'duracion': 9999})
check('acota la duración a 120 s', r.get('duracion') == 120 if c == 201 else False,
      f"({r.get('duracion') if isinstance(r, dict) else r})")

print("\n[6] Limpieza de las pruebas")
_, todos = api(adm, '/api/avisos/todos')
borrados = 0
for a in todos:
    if a['titulo'].startswith('ZZZ '):
        api(adm, f"/api/avisos/{a['id']}", 'DELETE')
        borrados += 1
print(f"      {borrados} avisos de prueba eliminados")
_, todos = api(adm, '/api/avisos/todos')
check('no quedaron restos', not any(a['titulo'].startswith('ZZZ ') for a in todos))

print("\n" + "=" * 60)
if fallos:
    print(f"RESULTADO: {len(fallos)} fallo(s):")
    for f in fallos:
        print("  -", f)
    raise SystemExit(1)
print("RESULTADO: el signage programa y despacha bien")
