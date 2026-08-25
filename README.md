# Sistema de Tickets — Cooperativa Reducto Ltda.

Sistema de gestión de turnos de atención para socios: emisión de tickets en el
kiosco de entrada, visualización en la TV de sala de espera y gestión desde los
puestos de atención.

## Puesta en marcha

```bash
pip install -r requirements.txt
python init_db.py          # crea tablas, departamentos y el usuario admin
python iniciar.py          # arranca el servidor
```

`init_db.py` pide la contraseña del administrador por teclado. Ya no existen
credenciales por defecto.

Si la base de datos viene de una versión anterior, correr una sola vez:

```bash
python migrar_db.py        # hace backup y actualiza el esquema
```

## Pantallas

| Pantalla | URL | Acceso | Dónde va |
|---|---|---|---|
| Kiosco | `/` | público | tablet/monitor en la entrada |
| Sala de espera | `/sala_espera` | público | televisor de la sala |
| Panel del operador | `/operador` | login | PC de cada ventanilla |
| Administración | `/admin` | rol admin | PC de administración |

`/socio` redirige al kiosco (se mantiene por compatibilidad con accesos
directos ya configurados).

## Identificación del socio

El socio entra su documento en el teclado del kiosco. Si está en el padrón, la
pantalla le muestra **nombre, N° de socio y documento** antes de avanzar, y esos
tres datos quedan guardados en el ticket: los ve el operador en su panel, salen
en el ticket impreso y quedan en el histórico.

El **N° de socio** es el número de la cooperativa, distinto del `id` interno de
la base. Es opcional: si un socio no lo tiene cargado, esa línea no se muestra y
todo lo demás funciona igual.

Si el documento no está en el padrón, la pantalla lo dice ("No encontramos esa
cédula en el padrón. Puede continuar igual") y el socio **saca su turno de todas
formas**, solo con la cédula. Identificarse nunca bloquea la atención.

La consulta al padrón arranca a los **5 dígitos**, la misma cantidad con la que
se habilita el botón "Siguiente". Los dos umbrales tienen que coincidir: si el
mínimo de búsqueda fuera mayor, habría cédulas cortas que el socio puede enviar
pero que el sistema nunca consultaría, y esos socios nunca serían reconocidos.

Si el socio aprieta "Siguiente" antes de que llegue la respuesta, el kiosco
espera su propia consulta en vez de avanzar sin los datos.

El padrón se carga desde `/admin/socios`, o se sincroniza solo desde el sistema
central configurando `TIKETERA_SOCIOS_API_URL`. De esa API se acepta el número
de socio en cualquiera de estos campos: `numero_socio`, `nro_socio` o `socio`.

Por privacidad, el endpoint público del kiosco devuelve únicamente nombre,
apellido y N° de socio. Nunca el teléfono ni el email, y tampoco el documento:
ese ya lo tiene el kiosco porque el socio lo acaba de tipear.

## Usuarios y puestos

Cada operador debe tener un **puesto** asignado: es el texto que el socio ve en
la TV ("DIRÍJASE A: VENTANILLA 1").

```bash
python gestionar_usuarios.py listar
python gestionar_usuarios.py crear jperez "Juan Perez" operador
python gestionar_usuarios.py puesto jperez "Ventanilla 1"
python gestionar_usuarios.py password jperez
```

También se administran desde `/admin/usuarios`.

## Atención en paralelo

Varios puestos pueden atender al mismo tiempo. Cada operador solo cierra sus
propios turnos y la TV muestra todos los llamados activos a la vez. Si un
operador intenta llamar un turno que otro puesto ya tomó, recibe un aviso.

## Numeración

Cada departamento tiene su propia secuencia diaria (`C-001`, `A-002`, `AH-001`),
que arranca de nuevo cada día calendario local.

**Reiniciar numeración** (en `/admin`) pone los contadores del día en cero pero
**no borra tickets**: el histórico se conserva íntegro.

## Configuración

Todo se controla con variables de entorno; no hay que editar código.

| Variable | Default | Para qué |
|---|---|---|
| `TIKETERA_PORT` | `5000` | puerto del servidor |
| `TIKETERA_SECRET_KEY` | se genera en `instance/` | clave de firma de sesiones |
| `TIKETERA_DATABASE_URI` | `sqlite:///tickets.db` | base de datos |
| `TIKETERA_TZ_OFFSET` | `-3` | zona horaria (Paraguay) |
| `TIKETERA_HTTPS` | `0` | `1` si se sirve detrás de HTTPS |
| `TIKETERA_AUTO_CALL` | `0` | `1` activa el llamado automático |
| `TIKETERA_AUTO_CALL_INTERVAL` | `300` | segundos entre llamados automáticos |
| `TIKETERA_CORS_ORIGINS` | vacío | orígenes externos permitidos en la API |
| `TIKETERA_SOCIOS_API_URL` | vacío | API externa de socios |
| `TIKETERA_SOCIOS_API_TOKEN` | vacío | token de esa API |

El **llamado automático** está apagado por defecto. Si se activa, solo actúa
cuando ningún puesto está atendiendo, para no interrumpir a un operador.

## API

Público (sin sesión): lo que necesitan el kiosco y la TV.

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/departamentos` | listar departamentos |
| POST | `/api/tickets` | emitir ticket |
| GET | `/api/socios/buscar?dni=` | nombre del socio (sin datos de contacto) |
| GET | `/api/tickets/llamados` | todos los turnos llamados ahora |
| GET | `/api/tickets/llamado` | el llamado más reciente |
| GET | `/api/tickets/ultimos_llamados` | últimos 5 finalizados |
| GET | `/api/estadisticas` | totales del día |

Requiere sesión de operador:

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/tickets/pendientes` | cola de espera (incluye datos del socio) |
| GET | `/api/tickets/mi_actual` | turno que atiende este puesto |
| PUT | `/api/tickets/<id>/llamar` | llamar un turno |
| PUT | `/api/tickets/<id>/finalizar` | finalizar un turno |
| POST | `/api/tickets/siguiente` | llamar al siguiente de la cola |
| GET | `/api/tickets/historico` | histórico con filtros |
| GET | `/api/socios/count` | cantidad de socios |

Requiere rol admin: el CRUD de `/api/socios`, `/api/usuarios`,
`/api/departamentos` y `POST /api/tickets/reiniciar`.

## Avisos de la TV

Se administran en `/admin/avisos` y tienen dos formas de mostrarse:

| | Dónde | Cuándo se ve |
|---|---|---|
| **Banner fijo** | franja abajo, en carrusel de 8 s | siempre, incluso mientras se llaman turnos |
| **Aviso** | pantalla completa, rota cada 12 s | solo cuando no hay un llamado reciente |

Un turno recién llamado siempre interrumpe los avisos de pantalla completa y
manda por 20 segundos. El banner no se interrumpe nunca.

Cada aviso puede llevar una **pieza gráfica** (los flyers ya diseñados). Si
tiene imagen, la TV la muestra sola a pantalla completa: la pieza ya trae su
texto y superponerle titulares la ensuciaría. Se aceptan PNG, JPG, GIF y WEBP
de hasta 6 MB; el archivo se valida por su contenido, no por la extensión, y
el servidor le pone un nombre propio.

Las imágenes se guardan en `static/avisos/`. Al reemplazar o borrar un aviso,
su archivo anterior se elimina para no acumular huérfanos.

**Resolución:** la TV escala la imagen al alto disponible (unos 690 px en una
pantalla 1080p). Un flyer de 500 px se ve algo blando; conviene subirlos de
**1000 px o más** de lado.

### Programación de campañas

Cada aviso tiene **vigencia** (desde / hasta) y **duración** en pantalla:

- Fuera de su rango de fechas la TV lo saca sola. Un flyer que dice "válido
  hasta el 30 de diciembre" se retira ese día sin que nadie se acuerde.
- El filtro por fecha se aplica **en el servidor**, así que una campaña vencida
  deja de salir aunque el televisor lleve semanas sin reiniciarse.
- La TV recarga la lista cada 2 minutos: dar de alta una campaña la pone al
  aire sin tocar el televisor.
- La duración es por pieza (3 a 120 s). Sugerido: 10 s para un titular,
  15-18 s para un flyer con mucho texto.

En `/admin/avisos` cada aviso muestra su estado: **EN PANTALLA**, **PROGRAMADO**
(con la fecha en que arranca), **VENCIDO** u **OCULTO**.

## Logo

Para instalar el logo institucional, guarde la imagen en cualquier carpeta y
ejecute:

```bash
python instalar_logo.py "C:\Users\Usuario\Downloads\logo.png"
```

El script verifica que sea una imagen válida y la copia a `static/` con el
nombre correcto. Para volver al logo de respaldo: `python instalar_logo.py --quitar`.

El logo aparece en las seis pantallas: kiosco, sala de espera (TV), login,
panel de administración, ticket en pantalla y ticket impreso.

El sistema busca `static/logo-cooperativa.*` en este orden: `.png`, `.jpg`,
`.jpeg`, `.svg`. El `.svg` incluido es solo un respaldo vectorial dibujado a
mano; conviene reemplazarlo por el archivo real. Un PNG con fondo transparente
se ve mejor que un JPG.

En el ticket impreso el logo sale en escala de grises con brillo y contraste
subidos, para que en papel térmico salga como dibujo de línea y no como una
mancha negra. Si su impresora igual lo imprime mal, se puede achicar o quitar
desde `.ticket-logo-img` en `templates/imprimir_ticket.html`.

## Estructura

```
TIKETERA/
├── app.py                    rutas y API
├── config.py                 configuración por variables de entorno
├── models.py                 modelos de base de datos
├── iniciar.py                arranque con waitress (producción)
├── init_db.py                inicialización
├── migrar_db.py              migración de esquema (idempotente)
├── gestionar_usuarios.py     alta de usuarios y contraseñas
├── instalar_logo.py          instala el logo institucional
├── pruebas.py                pruebas funcionales de la API
├── pruebas_pantallas.py      render y permisos de cada página
├── pruebas_dom.py            JS que apunta a elementos inexistentes
├── pruebas_kiosco.py         recorrido del kiosco con clics reales
├── cdp_cliente.py            driver de navegador (solo librería estándar)
├── ssh_manager.py            acceso SSH al servidor remoto (opcional)
├── docs/                     especificación original
├── _archivo/                 scripts viejos de depuración (se pueden borrar)
├── instance/                 base de datos y clave de sesión (NO versionar)
├── static/                   estilos y logo
└── templates/                pantallas HTML
```

## Pruebas

```bash
python pruebas.py            # API: permisos, numeración, atención en paralelo, privacidad
python pruebas_pantallas.py  # que todas las páginas rendericen y respeten los roles
python pruebas_dom.py        # que ningún JavaScript apunte a elementos inexistentes
```

Las tres corren sobre bases de datos temporales, sin tocar los datos reales.

`pruebas_dom.py` es la que atrapa un bug silencioso y grave: si el JavaScript
hace `getElementById` sobre un id que no está en el HTML, el navegador lanza
`TypeError` y la función muere sin dejar nada visible en pantalla. Así estuvo
roto el botón "Siguiente" del kiosco.

Para probar el kiosco haciendo clics de verdad en un navegador:

```bash
python iniciar.py            # en una terminal

# en otra, Edge con el puerto de depuración abierto
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
    --headless=new --remote-debugging-port=9222 `
    --user-data-dir=$env:TEMP\edge_pruebas about:blank

python pruebas_kiosco.py http://localhost:5000
```

No necesita playwright ni selenium: [cdp_cliente.py](cdp_cliente.py) habla el
protocolo de DevTools con la librería estándar de Python.

## Seguridad

- Las claves SSH viven en `~/.ssh/`, nunca dentro del proyecto.
- La clave de sesión no está en el código: sale de `TIKETERA_SECRET_KEY` o se
  genera en `instance/secret_key.txt`.
- Las pantallas públicas (kiosco y TV) nunca reciben cédula, teléfono ni email
  de los socios.
- Contraseñas: mínimo 8 caracteres, guardadas con hash.
- La carpeta `instance/` y cualquier clave están excluidas por `.gitignore`.
