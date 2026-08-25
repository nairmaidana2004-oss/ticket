"""Prueba las cuatro funciones nuevas contra el servidor real."""
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = 'http://localhost:5001'
fallos = []


def check(nombre, ok, detalle=''):
    print(f"  {'OK   ' if ok else 'FALLA'} {nombre} {detalle}")
    if not ok:
        fallos.append(nombre)


def cliente():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def pedir(op, ruta, metodo='GET', datos=None, form=None):
    cuerpo, headers = None, {}
    if datos is not None:
        cuerpo = json.dumps(datos).encode()
        headers['Content-Type'] = 'application/json'
    elif form is not None:
        cuerpo = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(BASE + ruta, data=cuerpo, headers=headers, method=metodo)
    try:
        with op.open(req) as r:
            texto = r.read().decode('utf-8', 'replace')
            try:
                return r.status, json.loads(texto)
            except json.JSONDecodeError:
                return r.status, texto
    except urllib.error.HTTPError as e:
        texto = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(texto)
        except json.JSONDecodeError:
            return e.code, texto


anon = cliente()
adm = cliente()
pedir(adm, '/login', 'POST', form={'username': 'admin', 'password': 'admin123'})

print("\n" + "=" * 68)
print(" 1) TABLERO DE GESTION")
print("=" * 68)
c, rep = pedir(adm, '/api/reportes/resumen')
check('el reporte responde', c == 200, f"(dio {c})")
t = rep['totales']
print(f"      turnos emitidos ....... {t['emitidos']}")
print(f"      atendidos ............. {t['atendidos']}")
print(f"      sin atender ........... {t['sin_atender']}")
print(f"      espera promedio ....... {t['espera_promedio']} min (mediana {t['espera_mediana']})")
print(f"      atencion promedio ..... {t['atencion_promedio']} min")
check('calcula espera promedio', t['espera_promedio'] is not None)
check('calcula atencion promedio', t['atencion_promedio'] is not None)
check('detecta abandonos', t['sin_atender'] > 0, f"({t['sin_atender']})")

pico = max(rep['por_hora'], key=lambda h: h['turnos'])
print(f"      hora pico ............. {pico['hora']:02d}:00 con {pico['turnos']} turnos")
check('identifica la hora pico', 7 <= pico['hora'] <= 17, f"(hora {pico['hora']})")
check('desglosa por departamento', len(rep['por_departamento']) == 4)
check('desglosa por operador', len(rep['por_operador']) >= 1)
print("      por departamento:")
for d in rep['por_departamento']:
    print(f"        {d['departamento']:<20} {d['turnos']:>4} turnos  "
          f"espera {d['espera_promedio']:>5} min  atencion {d['atencion_promedio']:>5} min")

c, _ = pedir(anon, '/api/reportes/resumen')
check('un anonimo NO puede ver el tablero', c == 401, f"(dio {c})")

c, csvtxt = pedir(adm, '/api/reportes/exportar')
check('exporta CSV', c == 200 and 'Ticket;Departamento' in csvtxt)
print(f"      CSV: {len(csvtxt.splitlines())} lineas")

print("\n" + "=" * 68)
print(" 2) AVISOS DE LA TV")
print("=" * 68)
c, avisos = pedir(anon, '/api/avisos')
check('la TV recibe los avisos sin login', c == 200 and len(avisos) >= 1,
      f"({len(avisos)} avisos)")
fijos = [a for a in avisos if a.get('banner')]
rotativos = [a for a in avisos if not a.get('banner')]
print(f"      banner fijo (carrusel de {len(fijos)}):")
for a in fijos:
    print(f"        {a['icono']} {a['titulo']} -> {a['destacado']}")
print(f"      a pantalla completa ({len(rotativos)}):")
for a in rotativos:
    print(f"        {a['icono']} {a['titulo']} -> {a['destacado']}")
check('cada aviso dice si es banner o rotativo',
      all('banner' in a for a in avisos))
c, r = pedir(anon, '/api/avisos', 'POST', {'titulo': 'pirata'})
check('un anonimo NO puede crear avisos', c == 401, f"(dio {c})")

print("\n" + "=" * 68)
print(" 3) ATENCION PREFERENCIAL")
print("=" * 68)
c, deps = pedir(anon, '/api/departamentos')
credito = next(d for d in deps if d['codigo'] == 'C')

# Tres comunes y despues uno preferencial
comunes = []
for i in range(3):
    c, t1 = pedir(anon, '/api/tickets', 'POST', {'departamento_id': credito['id']})
    comunes.append(t1['codigo_completo'])
c, pref = pedir(anon, '/api/tickets', 'POST',
                {'departamento_id': credito['id'], 'prioridad': 'adulto_mayor'})
print(f"      comunes emitidos: {comunes}")
print(f"      preferencial emitido: {pref['codigo_completo']} ({pref['prioridad_texto']})")
check('el ticket queda marcado', pref['prioridad'] == 'adulto_mayor')

c, cola = pedir(adm, f"/api/tickets/pendientes?departamento_id={credito['id']}")
print("      cola vista por el operador:")
for x in cola:
    print(f"        {x['codigo_completo']:<8} {x['estado']:<10} "
          f"{x['prioridad_texto'] or ''}")

# El invariante real: NINGUN comun puede quedar delante de un preferencial.
# No se compara contra una posicion fija, porque puede haber preferenciales
# de antes esperando y esos van primero, que es lo correcto.
posiciones_pref = [i for i, x in enumerate(cola) if x['prioridad_texto']]
posiciones_com = [i for i, x in enumerate(cola) if not x['prioridad_texto']]
check('todos los preferenciales van antes que los comunes',
      not posiciones_pref or not posiciones_com
      or max(posiciones_pref) < min(posiciones_com),
      f"(pref en {posiciones_pref}, comunes desde {min(posiciones_com) if posiciones_com else '-'})")
check('el preferencial nuevo se adelanto a sus tres comunes',
      next(i for i, x in enumerate(cola) if x['codigo_completo'] == pref['codigo_completo'])
      < min(i for i, x in enumerate(cola) if x['codigo_completo'] in comunes))

c, llamado = pedir(adm, '/api/tickets/siguiente', 'POST', {'departamento_id': credito['id']})
check('al llamar al siguiente sale un preferencial',
      bool(llamado.get('prioridad')),
      f"(llamo {llamado['codigo_completo']}, prioridad={llamado.get('prioridad_texto')})")

c, tv = pedir(anon, '/api/tickets/llamados')
en_tv = next((x for x in tv if x['codigo_completo'] == llamado['codigo_completo']), None)
check('la TV muestra la marca de preferencial',
      en_tv and en_tv['prioridad_texto'] == llamado['prioridad_texto'])

c, r = pedir(anon, '/api/tickets', 'POST',
             {'departamento_id': credito['id'], 'prioridad': 'inventado'})
check('rechaza un motivo invalido', c == 400, f"(dio {c})")

print("\n" + "=" * 68)
print(" 4) EL SEGUIMIENTO POR QR FUE RETIRADO")
print("=" * 68)
c, nuevo = pedir(anon, '/api/tickets', 'POST', {'departamento_id': credito['id']})
check('el ticket ya no expone token', 'token' not in nuevo)
c, _ = pedir(anon, '/turno/loquesea')
check('la pagina de seguimiento ya no existe', c == 404, f"(dio {c})")
c, _ = pedir(anon, '/qr/loquesea.svg')
check('el generador de QR ya no existe', c == 404, f"(dio {c})")

print("\n" + "=" * 68)
if fallos:
    print(f"RESULTADO: {len(fallos)} fallo(s):")
    for f in fallos:
        print("  -", f)
    raise SystemExit(1)
print("RESULTADO: las cuatro funciones andan")
