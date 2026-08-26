import csv
import io
import os
import secrets
import statistics
import threading
import time
from datetime import datetime, time as dtime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (Flask, Response, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)

from config import LOCAL_TZ, Config
from models import (Aviso, Departamento, HistorialTicket, SecuenciaTicket,
                    Socio, Ticket, Usuario, db, utcnow)

app = Flask(__name__)
app.config.from_object(Config)

# CORS solo sobre la API y solo para los origenes declarados en
# TIKETERA_CORS_ORIGINS. Sin esa variable no se habilita ningun origen externo,
# asi que flask-cors pasa a ser una dependencia opcional.
if app.config['CORS_ORIGINS']:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": app.config['CORS_ORIGINS']}},
         supports_credentials=True)

db.init_app(app)

# ==================== LOGIN MANAGER ====================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor inicie sesión para acceder a esta página."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


@login_manager.unauthorized_handler
def no_autorizado():
    """Las llamadas a la API deben recibir 401 JSON, no un redirect al login."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Autenticación requerida'}), 401
    flash(login_manager.login_message, login_manager.login_message_category)
    return redirect(url_for('login', next=request.full_path))


def admin_required(f):
    """Exige sesión iniciada y rol admin. Responde JSON en rutas /api/."""
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.rol != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'No autorizado'}), 403
            flash('Acceso denegado. Se requieren permisos de administrador.', 'danger')
            return redirect(url_for('operador'))
        return f(*args, **kwargs)
    return wrapper


# ==================== HELPERS DE FECHA ====================

def hoy_local():
    """Día calendario en la zona horaria de la cooperativa, no en UTC."""
    return datetime.now(LOCAL_TZ).date()


def _a_utc_naive(dt_local):
    """Pasa un datetime con zona al formato de almacenamiento (UTC sin tzinfo)."""
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def rango_utc_del_dia(dia=None):
    """Convierte un día local al rango [inicio, fin) equivalente en UTC.

    Las fechas se guardan en UTC; comparar directamente contra date.today()
    hacía que los tickets de la madrugada cayeran en el día anterior.
    """
    dia = dia or hoy_local()
    inicio_local = datetime.combine(dia, dtime.min, tzinfo=LOCAL_TZ)
    fin_local = inicio_local + timedelta(days=1)
    return _a_utc_naive(inicio_local), _a_utc_naive(fin_local)


def filtro_dia(query, dia=None):
    """Aplica al query el filtro 'creado durante el día local indicado'."""
    inicio, fin = rango_utc_del_dia(dia)
    return query.filter(Ticket.fecha_creacion >= inicio, Ticket.fecha_creacion < fin)


# ==================== HORARIO DE ATENCIÓN ====================

def _franja_del_dia(dia_semana):
    """Devuelve (apertura, cierre) como time, o None si ese día está cerrado."""
    texto = (app.config['HORARIO'].get(dia_semana) or '').strip()
    if not texto or '-' not in texto:
        return None
    try:
        desde, hasta = texto.split('-', 1)
        return (dtime.fromisoformat(desde.strip()), dtime.fromisoformat(hasta.strip()))
    except ValueError:
        app.logger.warning("Horario mal escrito para el día %s: %r", dia_semana, texto)
        return None


def estado_horario(ahora=None):
    """Dice si se pueden emitir turnos y por qué.

    Deja de emitir unos minutos antes del cierre: un turno sacado a las 16:58
    para un trámite de 20 minutos no se alcanza a atender y el socio espera
    para nada.
    """
    if not app.config['HORARIO_ACTIVO']:
        return {'abierto': True, 'emite': True, 'motivo': None,
                'apertura': None, 'cierre': None}

    ahora = ahora or datetime.now(LOCAL_TZ)
    franja = _franja_del_dia(ahora.weekday())

    if not franja:
        return {'abierto': False, 'emite': False, 'motivo': 'cerrado_hoy',
                'apertura': None, 'cierre': None, 'proximo': _proxima_apertura(ahora)}

    apertura, cierre = franja
    hora = ahora.time()
    datos = {'apertura': apertura.strftime('%H:%M'),
             'cierre': cierre.strftime('%H:%M')}

    if hora < apertura:
        return {**datos, 'abierto': False, 'emite': False, 'motivo': 'antes_de_abrir',
                'proximo': f"hoy {apertura.strftime('%H:%M')}"}
    if hora >= cierre:
        return {**datos, 'abierto': False, 'emite': False, 'motivo': 'cerrado',
                'proximo': _proxima_apertura(ahora)}

    corte = (datetime.combine(ahora.date(), cierre)
             - timedelta(minutes=app.config['CORTE_ANTES_DEL_CIERRE'])).time()
    if hora >= corte:
        return {**datos, 'abierto': True, 'emite': False, 'motivo': 'por_cerrar',
                'proximo': _proxima_apertura(ahora)}

    return {**datos, 'abierto': True, 'emite': True, 'motivo': None}


def _proxima_apertura(ahora):
    """Texto legible del próximo día y hora de atención."""
    DIAS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
    for adelanto in range(1, 8):
        siguiente = ahora + timedelta(days=adelanto)
        franja = _franja_del_dia(siguiente.weekday())
        if franja:
            cuando = 'mañana' if adelanto == 1 else DIAS[siguiente.weekday()]
            return f"{cuando} {franja[0].strftime('%H:%M')}"
    return None


@app.route('/api/horario', methods=['GET'])
def get_horario():
    """Lo consulta el kiosco para saber si puede emitir turnos."""
    return jsonify(estado_horario())


# ==================== ALERTAS DE COLA ====================

@app.route('/api/alertas', methods=['GET'])
@login_required
def get_alertas():
    """Colas que superaron el umbral, para reaccionar antes de que se dispare."""
    ahora = utcnow()
    umbral_espera = app.config['ALERTA_ESPERA_MIN']
    umbral_cola = app.config['ALERTA_COLA']

    pendientes = filtro_dia(
        Ticket.query.filter(Ticket.estado == Ticket.PENDIENTE)).all()

    por_depto = {}
    for t in pendientes:
        d = por_depto.setdefault(t.departamento_id, {
            'departamento': t.departamento.nombre if t.departamento else '—',
            'color': t.departamento.color if t.departamento else '#94a3b8',
            'en_espera': 0, '_esperas': []})
        d['en_espera'] += 1
        d['_esperas'].append((ahora - t.fecha_creacion).total_seconds() / 60)

    colas = []
    for dep_id, d in por_depto.items():
        espera_max = round(max(d['_esperas']), 1) if d['_esperas'] else 0
        motivos = []
        if espera_max >= umbral_espera:
            motivos.append('espera')
        if d['en_espera'] >= umbral_cola:
            motivos.append('cola')
        colas.append({
            'departamento_id': dep_id,
            'departamento': d['departamento'],
            'color': d['color'],
            'en_espera': d['en_espera'],
            'espera_maxima': espera_max,
            'espera_promedio': round(sum(d['_esperas']) / len(d['_esperas']), 1),
            'alerta': bool(motivos),
            'motivos': motivos,
        })

    colas.sort(key=lambda c: (not c['alerta'], -c['espera_maxima']))
    return jsonify({
        'umbral_espera': umbral_espera,
        'umbral_cola': umbral_cola,
        'hay_alerta': any(c['alerta'] for c in colas),
        'colas': colas,
    })


def orden_de_cola(query):
    """Ordena la cola: primero los preferenciales, después por hora de llegada.

    `prioridad.is_(None)` da 0 para los turnos con preferencia y 1 para los
    comunes, así que los preferenciales quedan adelante sin romper el orden de
    llegada dentro de cada grupo.
    """
    return query.order_by(Ticket.prioridad.is_(None), Ticket.fecha_creacion.asc())


# ==================== LOGO ====================

# Se prefiere el logo institucional real (PNG/JPG) si está presente;
# si no, se cae al SVG de respaldo.
_LOGO_CANDIDATOS = ('logo-cooperativa.png', 'logo-cooperativa.jpg',
                    'logo-cooperativa.jpeg', 'logo-cooperativa.svg')


@app.context_processor
def inyectar_logo():
    for nombre in _LOGO_CANDIDATOS:
        if os.path.exists(os.path.join(app.static_folder, nombre)):
            return {'logo_url': url_for('static', filename=nombre)}
    return {'logo_url': None}


# ==================== RUTAS DE PÁGINAS ====================

@app.route('/')
def index():
    return render_template('kiosco.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin' if current_user.rol == 'admin' else 'operador'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        user = Usuario.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.activo:
                flash('Usuario desactivado. Contacte al administrador.', 'danger')
                return render_template('login.html')

            login_user(user)
            user.ultimo_acceso = utcnow()
            db.session.commit()

            destino = _destino_seguro(request.args.get('next'))
            if not destino:
                destino = url_for('admin' if user.rol == 'admin' else 'operador')
            return redirect(destino)
        else:
            flash('Usuario o contraseña incorrectos', 'danger')

    return render_template('login.html')


def _destino_seguro(destino):
    """Evita open redirect: solo se aceptan rutas internas.

    'startswith("/")' no alcanzaba, porque '//sitio-externo.com' lo cumple y
    el navegador lo interpreta como URL absoluta.
    """
    if not destino:
        return None
    partes = urlparse(destino)
    if partes.scheme or partes.netloc:
        return None
    if not destino.startswith('/') or destino.startswith('//'):
        return None
    return destino


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/socio')
def socio():
    # La pantalla del socio es el kiosco. Se mantiene la ruta por compatibilidad
    # con los accesos directos ya configurados en las tablets.
    return redirect(url_for('index'))


@app.route('/sala_espera')
def sala_espera():
    return render_template('sala_espera.html')


@app.route('/operador')
@login_required
def operador():
    return render_template('operador.html', usuario=current_user)


@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html', usuario=current_user)


@app.route('/admin/socios')
@admin_required
def admin_socios():
    return render_template('socios.html', usuario=current_user)


@app.route('/imprimir_ticket')
def imprimir_ticket():
    return render_template('imprimir_ticket.html')


@app.route('/admin/usuarios')
@admin_required
def admin_usuarios():
    return render_template('usuarios.html', usuario=current_user)


@app.route('/admin/departamentos')
@admin_required
def admin_departamentos():
    return render_template('departamentos.html', usuario=current_user)


@app.route('/admin/historico')
@admin_required
def admin_historico():
    return render_template('historico.html', usuario=current_user)


@app.route('/admin/reportes')
@admin_required
def admin_reportes():
    return render_template('reportes.html', usuario=current_user)


@app.route('/admin/avisos')
@admin_required
def admin_avisos():
    return render_template('avisos.html', usuario=current_user)


# ==================== API DEPARTAMENTOS ====================

@app.route('/api/departamentos', methods=['GET'])
def get_departamentos():
    # Orden de creación, no alfabético: es el orden en que los socios están
    # acostumbrados a ver los botones en el kiosco (Créditos primero).
    departamentos = Departamento.query.order_by(Departamento.id).all()
    return jsonify([d.to_dict() for d in departamentos])


@app.route('/api/departamentos', methods=['POST'])
@admin_required
def crear_departamento():
    data = request.get_json(silent=True) or {}
    nombre = (data.get('nombre') or '').strip()
    codigo = (data.get('codigo') or '').strip().upper()

    if not nombre or not codigo:
        return jsonify({'error': 'Nombre y código son requeridos'}), 400

    if Departamento.query.filter_by(codigo=codigo).first():
        return jsonify({'error': 'Ya existe un departamento con ese código'}), 400

    departamento = Departamento(
        nombre=nombre,
        codigo=codigo,
        color=data.get('color', '#f4c33c'),
        icono=data.get('icono', '📋')
    )

    db.session.add(departamento)
    db.session.commit()

    return jsonify(departamento.to_dict()), 201


@app.route('/api/departamentos/<int:id>', methods=['PUT'])
@admin_required
def actualizar_departamento(id):
    departamento = db.session.get(Departamento, id)
    if not departamento:
        return jsonify({'error': 'Departamento no encontrado'}), 404

    data = request.get_json(silent=True) or {}

    nuevo_codigo = (data.get('codigo') or '').strip().upper()
    if nuevo_codigo and nuevo_codigo != departamento.codigo:
        if Departamento.query.filter_by(codigo=nuevo_codigo).first():
            return jsonify({'error': 'Ya existe un departamento con ese código'}), 400
        departamento.codigo = nuevo_codigo

    if data.get('nombre'):
        departamento.nombre = data['nombre'].strip()
    if data.get('color'):
        departamento.color = data['color']
    if data.get('icono'):
        departamento.icono = data['icono']

    db.session.commit()
    return jsonify(departamento.to_dict())


@app.route('/api/departamentos/<int:id>', methods=['DELETE'])
@admin_required
def eliminar_departamento(id):
    departamento = db.session.get(Departamento, id)
    if not departamento:
        return jsonify({'error': 'Departamento no encontrado'}), 404

    tickets_count = Ticket.query.filter_by(departamento_id=id).count()
    if tickets_count > 0:
        return jsonify({'error': f'No se puede eliminar, tiene {tickets_count} tickets asociados'}), 400

    SecuenciaTicket.query.filter_by(departamento_id=id).delete(synchronize_session=False)
    db.session.delete(departamento)
    db.session.commit()

    return jsonify({'message': 'Departamento eliminado'})


# ==================== NUMERACIÓN ====================

def siguiente_numero(departamento_id):
    """Reserva y devuelve el próximo número del día para el departamento."""
    dia = hoy_local()
    secuencia = SecuenciaTicket.query.filter_by(
        departamento_id=departamento_id, fecha=dia
    ).first()

    if not secuencia:
        secuencia = SecuenciaTicket(
            departamento_id=departamento_id, fecha=dia, ultimo_numero=0
        )
        db.session.add(secuencia)
        db.session.flush()

    secuencia.ultimo_numero += 1
    return secuencia.ultimo_numero


# ==================== API TICKETS (público) ====================

@app.route('/api/tickets', methods=['POST'])
def crear_ticket():
    data = request.get_json(silent=True) or {}
    departamento_id = data.get('departamento_id')
    nombre_socio = (data.get('nombre_socio') or '').strip()
    dni_socio = (data.get('dni_socio') or '').strip()
    numero_socio = (data.get('numero_socio') or '').strip()
    prioridad = (data.get('prioridad') or '').strip() or None

    if prioridad and prioridad not in Ticket.PRIORIDADES:
        return jsonify({'error': 'Motivo de preferencia inválido'}), 400

    # El horario se valida en el servidor: si solo lo controlara el kiosco,
    # bastaría con refrescar la pantalla para saltearlo.
    horario = estado_horario()
    if not horario['emite']:
        mensajes = {
            'cerrado_hoy': 'Hoy no hay atención.',
            'antes_de_abrir': f"La atención comienza a las {horario.get('apertura')}.",
            'cerrado': 'La atención del día ya terminó.',
            'por_cerrar': 'Ya no se emiten turnos: estamos por cerrar.',
        }
        detalle = mensajes.get(horario['motivo'], 'Fuera del horario de atención.')
        if horario.get('proximo'):
            detalle += f" Lo esperamos {horario['proximo']}."
        return jsonify({'error': detalle, 'fuera_de_horario': True}), 409

    departamento = db.session.get(Departamento, departamento_id) if departamento_id else None
    if not departamento:
        return jsonify({'error': 'Departamento no encontrado'}), 404

    # El número de socio y el nombre se toman del padrón, no de lo que manda el
    # kiosco: así el dato que queda en el histórico es el oficial.
    if dni_socio:
        socio = Socio.query.filter(Socio.dni == dni_socio,
                                   Socio.activo.is_(True)).first()
        if socio:
            numero_socio = socio.numero_socio or numero_socio
            nombre_socio = f"{socio.nombre} {socio.apellido}".strip()

    try:
        numero = siguiente_numero(departamento.id)
        ticket = Ticket(
            numero=numero,
            codigo_completo=f"{departamento.codigo}-{numero:03d}",
            departamento_id=departamento.id,
            estado=Ticket.PENDIENTE,
            nombre_socio=nombre_socio or None,
            dni_socio=dni_socio or None,
            numero_socio=numero_socio or None,
            prioridad=prioridad
        )
        db.session.add(ticket)
        accion = ('Ticket creado (preferencial: %s)' % Ticket.PRIORIDADES[prioridad]
                  if prioridad else 'Ticket creado')
        db.session.add(HistorialTicket(ticket=ticket, accion=accion))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error creando ticket")
        return jsonify({'error': 'No se pudo generar el ticket'}), 500

    # El kiosco es una pantalla pública: no le devolvemos datos personales.
    return jsonify(ticket.to_dict_publico()), 201


@app.route('/api/tickets/llamados', methods=['GET'])
def get_tickets_llamados():
    """Todos los turnos llamados en este momento, uno por puesto de atención."""
    tickets = Ticket.query.filter(
        Ticket.estado == Ticket.LLAMADO
    ).order_by(Ticket.fecha_atencion.desc()).all()
    return jsonify([t.to_dict_publico() for t in tickets])


@app.route('/api/tickets/llamado', methods=['GET'])
def get_ticket_llamado():
    """El llamado más reciente (es el que la TV anuncia por voz)."""
    ticket = Ticket.query.filter(
        Ticket.estado == Ticket.LLAMADO
    ).order_by(Ticket.fecha_atencion.desc()).first()
    return jsonify(ticket.to_dict_publico() if ticket else None)


@app.route('/api/tickets/ultimos_llamados', methods=['GET'])
def get_ultimos_llamados():
    tickets = Ticket.query.filter(
        Ticket.estado == Ticket.FINALIZADO,
        Ticket.fecha_atencion.isnot(None)
    ).order_by(Ticket.fecha_atencion.desc()).limit(5).all()
    return jsonify([t.to_dict_publico() for t in tickets])


@app.route('/api/estadisticas', methods=['GET'])
def get_estadisticas():
    inicio, fin = rango_utc_del_dia()
    base = Ticket.query.filter(
        Ticket.fecha_creacion >= inicio, Ticket.fecha_creacion < fin
    )
    return jsonify({
        'total_hoy': base.count(),
        'pendientes': base.filter(Ticket.estado == Ticket.PENDIENTE).count(),
        'llamados': base.filter(Ticket.estado == Ticket.LLAMADO).count(),
        'atendidos': base.filter(Ticket.estado == Ticket.FINALIZADO).count()
    })


# ==================== API TICKETS (operadores) ====================

@app.route('/api/tickets/pendientes', methods=['GET'])
@login_required
def get_tickets_pendientes():
    """Cola de espera. Requiere sesión: incluye nombre y cédula del socio."""
    departamento_id = request.args.get('departamento_id')

    query = Ticket.query.filter(Ticket.estado.in_(Ticket.ESTADOS_ACTIVOS))
    if departamento_id:
        query = query.filter(Ticket.departamento_id == departamento_id)

    tickets = orden_de_cola(filtro_dia(query)).all()
    return jsonify([t.to_dict() for t in tickets])


@app.route('/api/tickets/mi_actual', methods=['GET'])
@login_required
def get_mi_ticket_actual():
    """El ticket que ESTE operador está atendiendo.

    Antes el panel mostraba el último llamado del sistema, así que cada
    operador veía el ticket de su compañero.
    """
    ticket = Ticket.query.filter(
        Ticket.estado == Ticket.LLAMADO,
        Ticket.atendido_por_id == current_user.id
    ).order_by(Ticket.fecha_atencion.desc()).first()
    return jsonify(ticket.to_dict() if ticket else None)


def _cerrar_ticket_en_curso(usuario):
    """Finaliza el ticket que este operador tenía llamado.

    Antes se devolvían a 'Pendiente' TODOS los tickets llamados del sistema, con
    lo cual dos operadores trabajando a la vez se cancelaban mutuamente. Ahora
    cada puesto solo cierra lo suyo.
    """
    en_curso = Ticket.query.filter(
        Ticket.estado == Ticket.LLAMADO,
        Ticket.atendido_por_id == usuario.id
    ).all()

    for t in en_curso:
        t.estado = Ticket.FINALIZADO
        t.fecha_finalizacion = utcnow()
        db.session.add(HistorialTicket(
            ticket_id=t.id, usuario_id=usuario.id,
            accion='Ticket finalizado al llamar al siguiente'
        ))


def _marcar_llamado(ticket, usuario=None):
    ticket.estado = Ticket.LLAMADO
    ticket.fecha_atencion = utcnow()
    if usuario:
        ticket.atendido_por_id = usuario.id
        ticket.puesto_atencion = usuario.etiqueta_puesto
    else:
        ticket.atendido_por_id = None
        ticket.puesto_atencion = 'Recepción'

    db.session.add(HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=usuario.id if usuario else None,
        accion='Ticket llamado' if usuario else 'Ticket llamado automáticamente'
    ))


@app.route('/api/tickets/<int:id>/llamar', methods=['PUT'])
@login_required
def llamar_ticket(id):
    ticket = db.session.get(Ticket, id)
    if not ticket:
        return jsonify({'error': 'Ticket no encontrado'}), 404

    if ticket.estado == Ticket.FINALIZADO:
        return jsonify({'error': 'El ticket ya fue finalizado'}), 400

    if ticket.estado == Ticket.LLAMADO and ticket.atendido_por_id not in (None, current_user.id):
        return jsonify({
            'error': f'El ticket ya está siendo atendido en {ticket.puesto_atencion}'
        }), 409

    _cerrar_ticket_en_curso(current_user)
    _marcar_llamado(ticket, current_user)
    db.session.commit()

    return jsonify(ticket.to_dict())


@app.route('/api/tickets/<int:id>/finalizar', methods=['PUT'])
@login_required
def finalizar_ticket(id):
    ticket = db.session.get(Ticket, id)
    if not ticket:
        return jsonify({'error': 'Ticket no encontrado'}), 404

    ticket.estado = Ticket.FINALIZADO
    ticket.fecha_finalizacion = utcnow()
    if ticket.atendido_por_id is None:
        ticket.atendido_por_id = current_user.id
        ticket.puesto_atencion = current_user.etiqueta_puesto

    db.session.add(HistorialTicket(
        ticket_id=id, usuario_id=current_user.id, accion='Ticket finalizado'
    ))
    db.session.commit()

    return jsonify(ticket.to_dict())


def obtener_siguiente_ticket_logic(usuario=None, departamento_id=None):
    """Cierra lo que el puesto tenía en curso y llama al siguiente pendiente."""
    if usuario:
        _cerrar_ticket_en_curso(usuario)

    query = Ticket.query.filter(Ticket.estado == Ticket.PENDIENTE)
    if departamento_id:
        query = query.filter(Ticket.departamento_id == departamento_id)

    siguiente = orden_de_cola(filtro_dia(query)).first()

    if siguiente:
        _marcar_llamado(siguiente, usuario)

    db.session.commit()
    return siguiente


@app.route('/api/tickets/siguiente', methods=['POST'])
@login_required
def siguiente_ticket():
    data = request.get_json(silent=True) or {}
    ticket = obtener_siguiente_ticket_logic(
        usuario=current_user,
        departamento_id=data.get('departamento_id')
    )

    if ticket:
        return jsonify(ticket.to_dict())
    return jsonify({'message': 'No hay tickets pendientes'}), 200


@app.route('/api/tickets/historico', methods=['GET'])
@login_required
def get_tickets_historico():
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    departamento_id = request.args.get('departamento_id')
    estado = request.args.get('estado')

    query = Ticket.query

    try:
        if fecha_desde:
            inicio, _ = rango_utc_del_dia(datetime.strptime(fecha_desde, '%Y-%m-%d').date())
            query = query.filter(Ticket.fecha_creacion >= inicio)
        if fecha_hasta:
            _, fin = rango_utc_del_dia(datetime.strptime(fecha_hasta, '%Y-%m-%d').date())
            query = query.filter(Ticket.fecha_creacion < fin)
    except ValueError:
        return jsonify({'error': 'Formato de fecha inválido (se espera AAAA-MM-DD)'}), 400

    if departamento_id:
        query = query.filter(Ticket.departamento_id == departamento_id)
    if estado:
        query = query.filter(Ticket.estado == estado)

    tickets = query.order_by(Ticket.fecha_creacion.desc()).limit(2000).all()
    return jsonify([t.to_dict() for t in tickets])


# ==================== AVISOS DE LA TV ====================

def _fecha_opcional(valor):
    """Convierte 'AAAA-MM-DD' a date. Cadena vacía = sin límite."""
    valor = (valor or '').strip()
    if not valor:
        return None
    return datetime.strptime(valor, '%Y-%m-%d').date()


@app.route('/api/avisos', methods=['GET'])
def get_avisos():
    """Lo que la TV debe mostrar ahora: activos y dentro de su vigencia.

    El filtro por fecha se hace acá y no en la TV, para que una campaña
    vencida deje de salir aunque el televisor lleve semanas sin reiniciarse.
    """
    hoy = hoy_local()
    avisos = Aviso.query.filter_by(activo=True).order_by(
        Aviso.orden, Aviso.id).all()
    return jsonify([a.to_dict() for a in avisos if a.vigente(hoy)])


@app.route('/api/avisos/todos', methods=['GET'])
@admin_required
def get_avisos_todos():
    hoy = hoy_local()
    avisos = Aviso.query.order_by(Aviso.orden, Aviso.id).all()
    return jsonify([a.to_dict(dia=hoy) for a in avisos])


@app.route('/api/avisos', methods=['POST'])
@admin_required
def crear_aviso():
    data = request.get_json(silent=True) or {}
    titulo = (data.get('titulo') or '').strip()
    if not titulo:
        return jsonify({'error': 'El título es requerido'}), 400

    try:
        desde = _fecha_opcional(data.get('fecha_desde'))
        hasta = _fecha_opcional(data.get('fecha_hasta'))
    except ValueError:
        return jsonify({'error': 'Formato de fecha inválido (se espera AAAA-MM-DD)'}), 400

    if desde and hasta and desde > hasta:
        return jsonify({'error': 'La fecha de inicio no puede ser posterior a la de fin'}), 400

    aviso = Aviso(
        titulo=titulo,
        texto=(data.get('texto') or '').strip() or None,
        destacado=(data.get('destacado') or '').strip() or None,
        icono=(data.get('icono') or '📢').strip() or '📢',
        color=(data.get('color') or '#16a34a').strip(),
        orden=int(data.get('orden') or 0),
        activo=bool(data.get('activo', True)),
        banner=bool(data.get('banner', False)),
        fecha_desde=desde,
        fecha_hasta=hasta,
        duracion=max(3, min(120, int(data.get('duracion') or 12)))
    )
    db.session.add(aviso)
    db.session.commit()
    return jsonify(aviso.to_dict(dia=hoy_local())), 201


@app.route('/api/avisos/<int:id>', methods=['PUT'])
@admin_required
def actualizar_aviso(id):
    aviso = db.session.get(Aviso, id)
    if not aviso:
        return jsonify({'error': 'Aviso no encontrado'}), 404

    data = request.get_json(silent=True) or {}
    if data.get('titulo'):
        aviso.titulo = data['titulo'].strip()
    if 'texto' in data:
        aviso.texto = (data.get('texto') or '').strip() or None
    if 'destacado' in data:
        aviso.destacado = (data.get('destacado') or '').strip() or None
    if data.get('icono'):
        aviso.icono = data['icono'].strip()
    if data.get('color'):
        aviso.color = data['color'].strip()
    if 'orden' in data:
        aviso.orden = int(data.get('orden') or 0)
    if 'activo' in data:
        aviso.activo = bool(data['activo'])
    if 'banner' in data:
        aviso.banner = bool(data['banner'])

    try:
        if 'fecha_desde' in data:
            aviso.fecha_desde = _fecha_opcional(data['fecha_desde'])
        if 'fecha_hasta' in data:
            aviso.fecha_hasta = _fecha_opcional(data['fecha_hasta'])
    except ValueError:
        return jsonify({'error': 'Formato de fecha inválido (se espera AAAA-MM-DD)'}), 400

    if (aviso.fecha_desde and aviso.fecha_hasta
            and aviso.fecha_desde > aviso.fecha_hasta):
        db.session.rollback()
        return jsonify({'error': 'La fecha de inicio no puede ser posterior a la de fin'}), 400

    if 'duracion' in data:
        aviso.duracion = max(3, min(120, int(data.get('duracion') or 12)))

    db.session.commit()
    return jsonify(aviso.to_dict(dia=hoy_local()))


# Firmas de archivo: no se confía en la extensión que manda el navegador
FIRMAS_IMAGEN = {
    b'\x89PNG\r\n\x1a\n': '.png',
    b'\xff\xd8\xff': '.jpg',
    b'GIF87a': '.gif',
    b'GIF89a': '.gif',
}
MAX_IMAGEN_AVISO = 6 * 1024 * 1024   # 6 MB
CARPETA_AVISOS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'static', 'avisos')


def _extension_real(cabecera):
    for firma, ext in FIRMAS_IMAGEN.items():
        if cabecera.startswith(firma):
            return ext
    # WEBP: "RIFF....WEBP"
    if cabecera[:4] == b'RIFF' and cabecera[8:12] == b'WEBP':
        return '.webp'
    return None


@app.route('/api/avisos/<int:id>/imagen', methods=['POST'])
@admin_required
def subir_imagen_aviso(id):
    aviso = db.session.get(Aviso, id)
    if not aviso:
        return jsonify({'error': 'Aviso no encontrado'}), 404

    archivo = request.files.get('imagen')
    if not archivo or not archivo.filename:
        return jsonify({'error': 'No se recibió ninguna imagen'}), 400

    datos = archivo.read(MAX_IMAGEN_AVISO + 1)
    if len(datos) > MAX_IMAGEN_AVISO:
        return jsonify({'error': 'La imagen supera los 6 MB'}), 400
    if not datos:
        return jsonify({'error': 'El archivo está vacío'}), 400

    extension = _extension_real(datos[:16])
    if not extension:
        return jsonify({'error': 'El archivo no es una imagen (PNG, JPG, GIF o WEBP)'}), 400

    os.makedirs(CARPETA_AVISOS, exist_ok=True)

    # El nombre lo genera el servidor: nunca se usa el que manda el navegador,
    # que podría traer rutas o caracteres peligrosos.
    nombre = f"aviso_{aviso.id}_{secrets.token_hex(6)}{extension}"
    with open(os.path.join(CARPETA_AVISOS, nombre), 'wb') as f:
        f.write(datos)

    anterior = aviso.imagen
    aviso.imagen = nombre
    db.session.commit()

    # Se borra la imagen vieja para no dejar archivos huérfanos acumulándose
    if anterior:
        try:
            os.remove(os.path.join(CARPETA_AVISOS, anterior))
        except OSError:
            pass

    return jsonify(aviso.to_dict(dia=hoy_local()))


@app.route('/api/avisos/<int:id>/imagen', methods=['DELETE'])
@admin_required
def quitar_imagen_aviso(id):
    aviso = db.session.get(Aviso, id)
    if not aviso:
        return jsonify({'error': 'Aviso no encontrado'}), 404

    if aviso.imagen:
        try:
            os.remove(os.path.join(CARPETA_AVISOS, aviso.imagen))
        except OSError:
            pass
        aviso.imagen = None
        db.session.commit()

    return jsonify(aviso.to_dict(dia=hoy_local()))


@app.route('/api/avisos/<int:id>', methods=['DELETE'])
@admin_required
def eliminar_aviso(id):
    aviso = db.session.get(Aviso, id)
    if not aviso:
        return jsonify({'error': 'Aviso no encontrado'}), 404

    # Si tenía pieza gráfica, se borra también el archivo
    if aviso.imagen:
        try:
            os.remove(os.path.join(CARPETA_AVISOS, aviso.imagen))
        except OSError:
            pass

    db.session.delete(aviso)
    db.session.commit()
    return jsonify({'message': 'Aviso eliminado'})


# ==================== REPORTES DE GESTIÓN ====================

# Tope de seguridad: evita que un rango enorme cargue toda la base en memoria.
MAX_TICKETS_REPORTE = 200000


def _a_local(dt_utc):
    """Pasa un datetime guardado en UTC a la hora local de la cooperativa."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)


def _minutos(desde, hasta):
    """Diferencia en minutos, o None si falta alguna de las dos puntas."""
    if not desde or not hasta:
        return None
    minutos = (hasta - desde).total_seconds() / 60
    # Descarta valores absurdos: turnos que quedaron abiertos de un día para otro
    if minutos < 0 or minutos > 60 * 12:
        return None
    return minutos


def _promedio(valores):
    return round(statistics.mean(valores), 1) if valores else None


def _mediana(valores):
    return round(statistics.median(valores), 1) if valores else None


def _rango_pedido():
    """Lee desde/hasta de la query. Por defecto, el mes en curso."""
    hoy = hoy_local()
    try:
        desde = (datetime.strptime(request.args['desde'], '%Y-%m-%d').date()
                 if request.args.get('desde') else hoy.replace(day=1))
        hasta = (datetime.strptime(request.args['hasta'], '%Y-%m-%d').date()
                 if request.args.get('hasta') else hoy)
    except ValueError:
        return None, None, 'Formato de fecha inválido (se espera AAAA-MM-DD)'

    if desde > hasta:
        return None, None, 'La fecha "desde" no puede ser posterior a "hasta"'
    return desde, hasta, None


def _tickets_del_rango(desde, hasta):
    inicio, _ = rango_utc_del_dia(desde)
    _, fin = rango_utc_del_dia(hasta)
    return (Ticket.query
            .filter(Ticket.fecha_creacion >= inicio, Ticket.fecha_creacion < fin)
            .order_by(Ticket.fecha_creacion.asc())
            .limit(MAX_TICKETS_REPORTE)
            .all())


def _calcular_reporte(tickets, desde, hasta):
    """Arma todas las métricas a partir de los tickets del período.

    Se calcula en Python y no en SQL porque las agrupaciones son por hora y día
    LOCAL, y las fechas están guardadas en UTC.
    """
    hoy = hoy_local()

    esperas, atenciones = [], []
    por_depto, por_operador, por_hora, por_dia_sem, por_fecha = {}, {}, {}, {}, {}
    atendidos = sin_atender = en_cola = 0

    for t in tickets:
        creado = _a_local(t.fecha_creacion)
        dia = creado.date()

        espera = _minutos(t.fecha_creacion, t.fecha_atencion)
        atencion = _minutos(t.fecha_atencion, t.fecha_finalizacion)

        if t.estado == Ticket.FINALIZADO:
            atendidos += 1
        elif t.estado == Ticket.PENDIENTE:
            # Pendiente de un día ya cerrado = el socio se fue sin ser atendido
            if dia < hoy:
                sin_atender += 1
            else:
                en_cola += 1

        if espera is not None:
            esperas.append(espera)
        if atencion is not None:
            atenciones.append(atencion)

        # --- por departamento ---
        nombre_dep = t.departamento.nombre if t.departamento else 'Sin departamento'
        d = por_depto.setdefault(nombre_dep, {
            'departamento': nombre_dep,
            'color': t.departamento.color if t.departamento else '#94a3b8',
            'turnos': 0, '_esperas': [], '_atenciones': []
        })
        d['turnos'] += 1
        if espera is not None:
            d['_esperas'].append(espera)
        if atencion is not None:
            d['_atenciones'].append(atencion)

        # --- por operador (solo turnos efectivamente atendidos) ---
        if t.atendido_por_id or t.puesto_atencion:
            etiqueta = (t.atendido_por.nombre if t.atendido_por
                        else t.puesto_atencion)
            o = por_operador.setdefault(etiqueta, {
                'operador': etiqueta,
                'puesto': t.puesto_atencion,
                'turnos': 0, '_atenciones': []
            })
            o['turnos'] += 1
            if atencion is not None:
                o['_atenciones'].append(atencion)

        # --- por hora local ---
        h = por_hora.setdefault(creado.hour, {'hora': creado.hour, 'turnos': 0,
                                              '_esperas': []})
        h['turnos'] += 1
        if espera is not None:
            h['_esperas'].append(espera)

        # --- por día de la semana (0 = lunes) ---
        s = por_dia_sem.setdefault(creado.weekday(), {'dia': creado.weekday(),
                                                      'turnos': 0, '_esperas': []})
        s['turnos'] += 1
        if espera is not None:
            s['_esperas'].append(espera)

        # --- serie diaria ---
        f = por_fecha.setdefault(dia.isoformat(), {'fecha': dia.isoformat(),
                                                   'turnos': 0, '_esperas': []})
        f['turnos'] += 1
        if espera is not None:
            f['_esperas'].append(espera)

    def limpiar(grupo, clave_orden=None, con_atencion=True):
        salida = []
        for item in grupo.values():
            fila = {k: v for k, v in item.items() if not k.startswith('_')}
            if '_esperas' in item:
                fila['espera_promedio'] = _promedio(item['_esperas'])
            if con_atencion and '_atenciones' in item:
                fila['atencion_promedio'] = _promedio(item['_atenciones'])
            salida.append(fila)
        if clave_orden:
            salida.sort(key=clave_orden)
        return salida

    return {
        'rango': {'desde': desde.isoformat(), 'hasta': hasta.isoformat()},
        'totales': {
            'emitidos': len(tickets),
            'atendidos': atendidos,
            'sin_atender': sin_atender,
            'en_cola': en_cola,
            'espera_promedio': _promedio(esperas),
            'espera_mediana': _mediana(esperas),
            'espera_maxima': round(max(esperas), 1) if esperas else None,
            'atencion_promedio': _promedio(atenciones),
            # Cuántos turnos tienen cada dato: los tickets viejos no registraban
            # la finalización, así que el promedio de atención se calcula sobre
            # menos casos. Mostrarlo evita leer mal el número.
            'muestras_espera': len(esperas),
            'muestras_atencion': len(atenciones),
            'truncado': len(tickets) >= MAX_TICKETS_REPORTE
        },
        'por_departamento': limpiar(por_depto, lambda x: -x['turnos']),
        'por_operador': limpiar(por_operador, lambda x: -x['turnos']),
        'por_hora': limpiar(por_hora, lambda x: x['hora'], con_atencion=False),
        'por_dia_semana': limpiar(por_dia_sem, lambda x: x['dia'], con_atencion=False),
        'serie_diaria': limpiar(por_fecha, lambda x: x['fecha'], con_atencion=False),
    }


@app.route('/api/reportes/resumen', methods=['GET'])
@admin_required
def reporte_resumen():
    desde, hasta, error = _rango_pedido()
    if error:
        return jsonify({'error': error}), 400
    return jsonify(_calcular_reporte(_tickets_del_rango(desde, hasta), desde, hasta))


@app.route('/api/reportes/exportar', methods=['GET'])
@admin_required
def reporte_exportar():
    """Descarga el detalle de turnos del período en CSV, para abrir en Excel."""
    desde, hasta, error = _rango_pedido()
    if error:
        return jsonify({'error': error}), 400

    tickets = _tickets_del_rango(desde, hasta)

    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=';')  # Excel en español usa ;
    escritor.writerow([
        'Ticket', 'Departamento', 'Estado', 'Fecha', 'Hora emisión',
        'Hora llamado', 'Hora finalización', 'Espera (min)', 'Atención (min)',
        'Puesto', 'Operador', 'N° socio', 'Documento', 'Socio'
    ])

    for t in tickets:
        creado = _a_local(t.fecha_creacion)
        llamado = _a_local(t.fecha_atencion) if t.fecha_atencion else None
        fin = _a_local(t.fecha_finalizacion) if t.fecha_finalizacion else None
        espera = _minutos(t.fecha_creacion, t.fecha_atencion)
        atencion = _minutos(t.fecha_atencion, t.fecha_finalizacion)

        def coma(valor):
            # Excel en español espera coma decimal
            return ('%.1f' % valor).replace('.', ',') if valor is not None else ''

        escritor.writerow([
            t.codigo_completo,
            t.departamento.nombre if t.departamento else '',
            t.estado,
            creado.strftime('%d/%m/%Y'),
            creado.strftime('%H:%M'),
            llamado.strftime('%H:%M') if llamado else '',
            fin.strftime('%H:%M') if fin else '',
            coma(espera), coma(atencion),
            t.puesto_atencion or '',
            t.atendido_por.nombre if t.atendido_por else '',
            t.numero_socio or '', t.dni_socio or '', t.nombre_socio or ''
        ])

    # BOM para que Excel reconozca los acentos
    datos = '﻿' + buffer.getvalue()
    nombre = f"turnos_{desde.isoformat()}_a_{hasta.isoformat()}.csv"
    return Response(
        datos,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{nombre}"'}
    )


@app.route('/api/tickets/reiniciar', methods=['POST'])
@admin_required
def reiniciar_numeracion():
    """Reinicia el contador diario SIN borrar tickets.

    La versión anterior hacía DELETE de los tickets del día, con lo cual se
    perdía el histórico de la jornada de forma irreversible.
    """
    data = request.get_json(silent=True) or {}
    departamento_id = data.get('departamento_id')
    dia = hoy_local()

    try:
        query = SecuenciaTicket.query.filter_by(fecha=dia)
        if departamento_id:
            query = query.filter_by(departamento_id=departamento_id)

        secuencias = query.all()
        for s in secuencias:
            s.ultimo_numero = 0

        if not secuencias and departamento_id:
            db.session.add(SecuenciaTicket(
                departamento_id=departamento_id, fecha=dia, ultimo_numero=0
            ))

        db.session.commit()
        app.logger.info(
            "Numeración reiniciada por %s (departamento=%s)",
            current_user.username, departamento_id or 'todos'
        )
        return jsonify({
            'message': 'Numeración reiniciada. Los tickets del día se conservan en el histórico.'
        })
    except Exception:
        db.session.rollback()
        app.logger.exception("Error reiniciando numeración")
        return jsonify({'error': 'Error interno al reiniciar'}), 500


# ==================== API SOCIOS ====================

EXTERNAL_API_CONFIG = {
    'URL': os.environ.get('TIKETERA_SOCIOS_API_URL'),
    'AUTH_TOKEN': os.environ.get('TIKETERA_SOCIOS_API_TOKEN'),
    'TIMEOUT': 5
}


def fetch_socios_externos(dni=None):
    """Consulta la API externa de socios, si está configurada."""
    if not EXTERNAL_API_CONFIG['URL']:
        return None

    try:
        import json
        import urllib.parse
        import urllib.request

        url = EXTERNAL_API_CONFIG['URL']
        if dni:
            url += '?' + urllib.parse.urlencode({'dni': dni})

        headers = {'Content-Type': 'application/json'}
        if EXTERNAL_API_CONFIG['AUTH_TOKEN']:
            headers['Authorization'] = EXTERNAL_API_CONFIG['AUTH_TOKEN']

        req = urllib.request.Request(url, headers=headers, method='GET')

        with urllib.request.urlopen(req, timeout=EXTERNAL_API_CONFIG['TIMEOUT']) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode())
                if dni and isinstance(data, list) and len(data) > 0:
                    return data[0]
                return data
    except Exception as e:
        app.logger.warning("Error conectando a API externa de socios: %s", e)
        return None


@app.route('/api/socios/buscar', methods=['GET'])
def buscar_socio():
    """Búsqueda por cédula exacta desde el kiosco.

    Es la única ruta pública de socios y devuelve solo nombre y apellido,
    lo justo para saludar al socio en pantalla.
    """
    dni = (request.args.get('dni') or '').strip()
    if not dni or len(dni) < 5:
        return jsonify({'error': 'DNI requerido'}), 400

    socio = Socio.query.filter(Socio.dni == dni, Socio.activo.is_(True)).first()
    if socio:
        return jsonify(socio.to_dict_publico())

    externo = fetch_socios_externos(dni=dni)
    if externo and isinstance(externo, dict) and externo.get('nombre'):
        # La API externa puede nombrar el campo de varias formas
        nro = (externo.get('numero_socio') or externo.get('nro_socio')
               or externo.get('socio') or None)
        try:
            nuevo_socio = Socio(
                numero_socio=str(nro) if nro else None,
                dni=str(externo.get('dni', dni)),
                nombre=externo.get('nombre'),
                apellido=externo.get('apellido', ''),
                telefono=externo.get('telefono'),
                email=externo.get('email')
            )
            db.session.add(nuevo_socio)
            db.session.commit()
            return jsonify(nuevo_socio.to_dict_publico())
        except Exception:
            db.session.rollback()
            app.logger.exception("Error guardando socio externo")
            return jsonify({
                'numero_socio': str(nro) if nro else None,
                'nombre': externo.get('nombre'),
                'apellido': externo.get('apellido', '')
            })

    return jsonify(None)


@app.route('/api/socios', methods=['GET'])
@admin_required
def get_socios():
    externos = fetch_socios_externos()
    if externos is not None:
        return jsonify(externos)

    socios = Socio.query.filter(Socio.activo.is_(True)).order_by(
        Socio.apellido, Socio.nombre
    ).all()
    return jsonify([s.to_dict() for s in socios])


@app.route('/api/socios/count', methods=['GET'])
@login_required
def get_socios_count():
    return jsonify({'count': Socio.query.filter(Socio.activo.is_(True)).count()})


@app.route('/api/socios', methods=['POST'])
@admin_required
def crear_socio():
    data = request.get_json(silent=True) or {}

    dni = (data.get('dni') or '').strip()
    nombre = (data.get('nombre') or '').strip()
    apellido = (data.get('apellido') or '').strip()
    numero_socio = (data.get('numero_socio') or '').strip()

    if not dni or not nombre or not apellido:
        return jsonify({'error': 'DNI, nombre y apellido son requeridos'}), 400

    if Socio.query.filter(Socio.dni == dni).first():
        return jsonify({'error': 'Ya existe un socio con ese DNI'}), 400

    if numero_socio and Socio.query.filter(Socio.numero_socio == numero_socio).first():
        return jsonify({'error': 'Ya existe un socio con ese número de socio'}), 400

    socio = Socio(
        numero_socio=numero_socio or None,
        dni=dni,
        nombre=nombre,
        apellido=apellido,
        telefono=data.get('telefono'),
        email=data.get('email')
    )
    db.session.add(socio)
    db.session.commit()

    return jsonify(socio.to_dict()), 201


@app.route('/api/socios/<int:id>', methods=['PUT'])
@admin_required
def actualizar_socio(id):
    socio = db.session.get(Socio, id)
    if not socio:
        return jsonify({'error': 'Socio no encontrado'}), 404

    data = request.get_json(silent=True) or {}

    nuevo_dni = (data.get('dni') or '').strip()
    if nuevo_dni and nuevo_dni != socio.dni:
        if Socio.query.filter(Socio.dni == nuevo_dni).first():
            return jsonify({'error': 'Ya existe un socio con ese DNI'}), 400
        socio.dni = nuevo_dni

    if 'numero_socio' in data:
        nuevo_nro = (data.get('numero_socio') or '').strip() or None
        if nuevo_nro != socio.numero_socio:
            if nuevo_nro and Socio.query.filter(Socio.numero_socio == nuevo_nro).first():
                return jsonify({'error': 'Ya existe un socio con ese número de socio'}), 400
            socio.numero_socio = nuevo_nro

    if data.get('nombre'):
        socio.nombre = data['nombre'].strip()
    if data.get('apellido'):
        socio.apellido = data['apellido'].strip()

    if 'telefono' in data:
        socio.telefono = data.get('telefono')
    if 'email' in data:
        socio.email = data.get('email')

    db.session.commit()
    return jsonify(socio.to_dict())


@app.route('/api/socios/<int:id>', methods=['DELETE'])
@admin_required
def eliminar_socio(id):
    socio = db.session.get(Socio, id)
    if not socio:
        return jsonify({'error': 'Socio no encontrado'}), 404

    socio.activo = False  # baja lógica
    db.session.commit()

    return jsonify({'message': 'Socio eliminado'})


# ==================== API USUARIOS ====================

@app.route('/api/usuarios', methods=['GET'])
@admin_required
def get_usuarios():
    usuarios = Usuario.query.order_by(Usuario.nombre).all()
    return jsonify([u.to_dict() for u in usuarios])


@app.route('/api/usuarios', methods=['POST'])
@admin_required
def crear_usuario():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    nombre = (data.get('nombre') or '').strip()
    password = data.get('password') or ''
    rol = data.get('rol', 'operador')
    puesto = (data.get('puesto') or '').strip()

    if not username or not nombre or not password:
        return jsonify({'error': 'Usuario, nombre y contraseña son requeridos'}), 400

    if rol not in ('admin', 'operador'):
        return jsonify({'error': 'Rol inválido'}), 400

    if len(password) < 8:
        return jsonify({'error': 'La contraseña debe tener al menos 8 caracteres'}), 400

    if Usuario.query.filter_by(username=username).first():
        return jsonify({'error': 'El nombre de usuario ya existe'}), 400

    usuario = Usuario(
        username=username,
        nombre=nombre,
        rol=rol,
        puesto=puesto or None,
        activo=bool(data.get('activo', True))
    )
    usuario.set_password(password)

    db.session.add(usuario)
    db.session.commit()

    return jsonify(usuario.to_dict()), 201


@app.route('/api/usuarios/<int:id>', methods=['PUT'])
@admin_required
def actualizar_usuario(id):
    usuario = db.session.get(Usuario, id)
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    data = request.get_json(silent=True) or {}

    nuevo_username = (data.get('username') or '').strip()
    if nuevo_username and nuevo_username != usuario.username:
        if Usuario.query.filter_by(username=nuevo_username).first():
            return jsonify({'error': 'El nombre de usuario ya existe'}), 400
        usuario.username = nuevo_username

    if data.get('nombre'):
        usuario.nombre = data['nombre'].strip()

    if data.get('rol'):
        if data['rol'] not in ('admin', 'operador'):
            return jsonify({'error': 'Rol inválido'}), 400
        if id == current_user.id and data['rol'] != 'admin':
            return jsonify({'error': 'No puedes quitarte tu propio rol de administrador'}), 400
        usuario.rol = data['rol']

    if 'activo' in data:
        if id == current_user.id and not data['activo']:
            return jsonify({'error': 'No puedes desactivar tu propia cuenta'}), 400
        usuario.activo = bool(data['activo'])

    if 'puesto' in data:
        usuario.puesto = (data['puesto'] or '').strip() or None

    if data.get('password'):
        if len(data['password']) < 8:
            return jsonify({'error': 'La contraseña debe tener al menos 8 caracteres'}), 400
        usuario.set_password(data['password'])

    db.session.commit()
    return jsonify(usuario.to_dict())


@app.route('/api/usuarios/<int:id>', methods=['DELETE'])
@admin_required
def eliminar_usuario(id):
    usuario = db.session.get(Usuario, id)
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    if usuario.id == current_user.id:
        return jsonify({'error': 'No puedes eliminar tu propia cuenta'}), 400

    # Baja lógica: se conserva la trazabilidad del histórico.
    usuario.activo = False
    db.session.commit()
    return jsonify({'message': 'Usuario desactivado'})


# ==================== MANEJO DE ERRORES ====================

@app.errorhandler(404)
def no_encontrado(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Recurso no encontrado'}), 404
    return render_template('login.html'), 404


@app.errorhandler(500)
def error_interno(e):
    db.session.rollback()
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Error interno del servidor'}), 500
    return "Error interno del servidor", 500


# ==================== LLAMADO AUTOMÁTICO ====================

def auto_caller_worker():
    """Llama tickets sin operador. Apagado por defecto (TIKETERA_AUTO_CALL=1).

    Solo actúa cuando NO hay ningún puesto atendiendo, para no interrumpir a un
    operador que está con un socio.
    """
    intervalo = app.config['AUTO_CALL_INTERVAL']
    app.logger.info("[AUTO-CALLER] Activo. Intervalo: %s segundos.", intervalo)

    while True:
        try:
            time.sleep(intervalo)
            with app.app_context():
                if Ticket.query.filter_by(estado=Ticket.LLAMADO).count() > 0:
                    continue  # hay un puesto atendiendo, no interrumpir
                if Ticket.query.filter_by(estado=Ticket.PENDIENTE).count() == 0:
                    continue
                ticket = obtener_siguiente_ticket_logic(usuario=None)
                if ticket:
                    app.logger.info("[AUTO-CALLER] Ticket llamado: %s", ticket.codigo_completo)
        except Exception:
            app.logger.exception("[AUTO-CALLER] Error")


def _avisar_credenciales_por_defecto():
    """Alerta si quedaron contraseñas de instalación sin cambiar."""
    inseguras = []
    for username, password in (('admin', 'admin123'), ('operador', 'operador123')):
        u = Usuario.query.filter_by(username=username).first()
        if u and u.check_password(password):
            inseguras.append(username)
    if inseguras:
        print("\n" + "!" * 62)
        print("  ATENCION: contrasenas por defecto sin cambiar: " + ", ".join(inseguras))
        print("  Ejecute:  python gestionar_usuarios.py password <usuario>")
        print("!" * 62 + "\n", flush=True)


if __name__ == '__main__':
    with app.app_context():
        _avisar_credenciales_por_defecto()

    es_proceso_principal = (
        os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        or not app.config.get('DEBUG')
    )
    if app.config['AUTO_CALL_ENABLED'] and es_proceso_principal:
        if not any(t.name == 'AutoCallerThread' for t in threading.enumerate()):
            threading.Thread(
                target=auto_caller_worker, name='AutoCallerThread', daemon=True
            ).start()

    puerto = int(os.environ.get('TIKETERA_PORT', '5000'))
    print(f"Sistema de Tickets iniciado en http://0.0.0.0:{puerto}", flush=True)
    app.run(debug=False, host='0.0.0.0', port=puerto)
