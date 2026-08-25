from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def _iso_utc(valor):
    """Serializa un datetime naive (guardado en UTC) como ISO-8601 con offset.

    Sin el sufijo de zona, el navegador interpreta la fecha como hora local y
    las pantallas muestran un desfase de varias horas.
    """
    if not valor:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.isoformat()


def utcnow():
    """Momento actual en UTC, sin tzinfo (formato de almacenamiento)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Usuario(UserMixin, db.Model):
    """Modelo de usuario para autenticación del sistema"""
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(20), default='operador')  # admin, operador
    activo = db.Column(db.Boolean, default=True)
    puesto = db.Column(db.String(50), nullable=True)  # Ej: Puesto 1, Ventanilla A
    fecha_creacion = db.Column(db.DateTime, default=utcnow)
    ultimo_acceso = db.Column(db.DateTime, nullable=True)

    @property
    def is_active(self):
        return self.activo

    @property
    def etiqueta_puesto(self):
        """Texto que ve el socio en la TV: 'Puesto 2', 'Ventanilla A'..."""
        return self.puesto or self.nombre

    def set_password(self, password):
        """Genera el hash de la contraseña"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifica la contraseña contra el hash"""
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'nombre': self.nombre,
            'rol': self.rol,
            'puesto': self.puesto,
            'activo': self.activo,
            'fecha_creacion': _iso_utc(self.fecha_creacion),
            'ultimo_acceso': _iso_utc(self.ultimo_acceso)
        }


class Departamento(db.Model):
    __tablename__ = 'departamentos'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    codigo = db.Column(db.String(10), nullable=False, unique=True)
    color = db.Column(db.String(20), default='#16a34a')  # Color para UI
    icono = db.Column(db.String(50), default='📋')  # Emoji para UI

    tickets = db.relationship('Ticket', backref='departamento', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'codigo': self.codigo,
            'color': self.color,
            'icono': self.icono
        }


class Ticket(db.Model):
    __tablename__ = 'tickets'

    # Estados validos del ciclo de vida de un ticket
    PENDIENTE = 'Pendiente'
    LLAMADO = 'Llamado'
    FINALIZADO = 'Finalizado'
    ESTADOS = (PENDIENTE, LLAMADO, FINALIZADO)
    ESTADOS_ACTIVOS = (PENDIENTE, LLAMADO)

    # Motivos de atención preferencial (Ley 4934). El orden no importa:
    # todos pesan igual frente a un turno común.
    PRIORIDADES = {
        'adulto_mayor': 'Adulto mayor',
        'embarazada': 'Embarazada',
        'discapacidad': 'Persona con discapacidad',
    }

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer, nullable=False)
    codigo_completo = db.Column(db.String(20), nullable=False)  # Ej: C-001
    # Motivo de preferencia, o NULL si es un turno común
    prioridad = db.Column(db.String(30), nullable=True, index=True)
    departamento_id = db.Column(db.Integer, db.ForeignKey('departamentos.id'), nullable=False)
    estado = db.Column(db.String(20), default=PENDIENTE, index=True)
    fecha_creacion = db.Column(db.DateTime, default=utcnow, index=True)
    fecha_atencion = db.Column(db.DateTime, nullable=True)
    fecha_finalizacion = db.Column(db.DateTime, nullable=True)
    # Datos del socio que saco el turno
    nombre_socio = db.Column(db.String(200), nullable=True)
    dni_socio = db.Column(db.String(20), nullable=True)
    numero_socio = db.Column(db.String(20), nullable=True)
    puesto_atencion = db.Column(db.String(50), nullable=True)  # El puesto que lo llamó
    # Operador que lo llamó: permite que varios puestos atiendan en paralelo
    atendido_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    historial = db.relationship('HistorialTicket', backref='ticket', lazy=True)
    atendido_por = db.relationship('Usuario', backref='tickets_atendidos', lazy=True)

    def to_dict(self):
        """Serialización completa. Solo para pantallas autenticadas."""
        datos = self.to_dict_publico()
        datos.update({
            'nombre_socio': self.nombre_socio,
            'dni_socio': self.dni_socio,
            'numero_socio': self.numero_socio,
            'atendido_por': self.atendido_por.nombre if self.atendido_por else None,
        })
        return datos

    def to_dict_publico(self):
        """Serialización sin datos personales.

        Se usa en el kiosco y en la TV de sala de espera, que son pantallas
        públicas: nunca deben exponer cédula ni nombre del socio.
        """
        return {
            'id': self.id,
            'numero': self.numero,
            'codigo_completo': self.codigo_completo,
            'departamento_id': self.departamento_id,
            'departamento': self.departamento.to_dict() if self.departamento else None,
            'estado': self.estado,
            'fecha_creacion': _iso_utc(self.fecha_creacion),
            'fecha_atencion': _iso_utc(self.fecha_atencion),
            'fecha_finalizacion': _iso_utc(self.fecha_finalizacion),
            'puesto_atencion': self.puesto_atencion,
            'prioridad': self.prioridad,
            'prioridad_texto': self.PRIORIDADES.get(self.prioridad) if self.prioridad else None
        }


class Aviso(db.Model):
    """Mensaje institucional que rota en la TV de sala de espera.

    Convierte el tiempo de espera en un espacio de comunicación: tasas,
    requisitos, campañas, avisos de asamblea.
    """
    __tablename__ = 'avisos'

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(120), nullable=False)
    texto = db.Column(db.Text, nullable=True)
    destacado = db.Column(db.String(120), nullable=True)  # Ej: "Desde 18% anual"
    icono = db.Column(db.String(20), nullable=True, default='📢')
    color = db.Column(db.String(20), nullable=True, default='#16a34a')
    orden = db.Column(db.Integer, nullable=False, default=0)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    # Banner: franja fija abajo de la pantalla, siempre visible. A diferencia
    # de los avisos rotativos, no se interrumpe cuando se llama un turno.
    banner = db.Column(db.Boolean, nullable=False, default=False)
    # Nombre del archivo dentro de static/avisos/. Si hay imagen, la TV la
    # muestra a pantalla completa: la pieza de diseño ya trae su propio texto.
    imagen = db.Column(db.String(120), nullable=True)
    # Vigencia de la campaña. Fuera de este rango el aviso no sale en la TV,
    # sin que nadie tenga que acordarse de bajarlo.
    fecha_desde = db.Column(db.Date, nullable=True)
    fecha_hasta = db.Column(db.Date, nullable=True)
    # Segundos en pantalla. Una pieza cargada de texto necesita más tiempo
    # que un titular corto.
    duracion = db.Column(db.Integer, nullable=False, default=12)
    fecha_creacion = db.Column(db.DateTime, default=utcnow)

    def vigente(self, dia):
        """True si el aviso corresponde mostrarlo en la fecha indicada."""
        if not self.activo:
            return False
        if self.fecha_desde and dia < self.fecha_desde:
            return False
        if self.fecha_hasta and dia > self.fecha_hasta:
            return False
        return True

    def estado_vigencia(self, dia):
        """Etiqueta para el panel: programado / vencido / vigente / oculto."""
        if not self.activo:
            return 'oculto'
        if self.fecha_desde and dia < self.fecha_desde:
            return 'programado'
        if self.fecha_hasta and dia > self.fecha_hasta:
            return 'vencido'
        return 'vigente'

    def to_dict(self, dia=None):
        return {
            'id': self.id,
            'titulo': self.titulo,
            'texto': self.texto,
            'destacado': self.destacado,
            'icono': self.icono or '📢',
            'color': self.color or '#16a34a',
            'orden': self.orden,
            'activo': self.activo,
            'banner': bool(self.banner),
            'imagen': f'/static/avisos/{self.imagen}' if self.imagen else None,
            'fecha_desde': self.fecha_desde.isoformat() if self.fecha_desde else None,
            'fecha_hasta': self.fecha_hasta.isoformat() if self.fecha_hasta else None,
            'duracion': self.duracion or 12,
            'estado_vigencia': self.estado_vigencia(dia) if dia else None
        }


class SecuenciaTicket(db.Model):
    """Contador de numeración diaria por departamento.

    Reemplaza el cálculo MAX(numero)+1, que tenía dos problemas: dos socios
    generando ticket a la vez podían recibir el mismo número, y "reiniciar la
    numeración" obligaba a borrar los tickets del día.
    """
    __tablename__ = 'secuencias_ticket'
    __table_args__ = (
        db.UniqueConstraint('departamento_id', 'fecha', name='uq_secuencia_depto_fecha'),
    )

    id = db.Column(db.Integer, primary_key=True)
    departamento_id = db.Column(db.Integer, db.ForeignKey('departamentos.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)  # día calendario local
    ultimo_numero = db.Column(db.Integer, nullable=False, default=0)


class HistorialTicket(db.Model):
    __tablename__ = 'historial_ticket'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    accion = db.Column(db.String(100), nullable=False)
    fecha = db.Column(db.DateTime, default=utcnow)

    usuario = db.relationship('Usuario', backref='historial_acciones', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'usuario': self.usuario.nombre if self.usuario else 'Sistema',
            'accion': self.accion,
            'fecha': _iso_utc(self.fecha)
        }


class Socio(db.Model):
    __tablename__ = 'socios'

    id = db.Column(db.Integer, primary_key=True)
    # Numero de socio de la cooperativa. Es distinto del id interno de la base:
    # el id es un autoincremental sin significado para el socio.
    numero_socio = db.Column(db.String(20), nullable=True, unique=True, index=True)
    dni = db.Column(db.String(20), nullable=False, unique=True)
    nombre = db.Column(db.String(200), nullable=False)
    apellido = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    fecha_registro = db.Column(db.DateTime, default=utcnow)
    activo = db.Column(db.Boolean, default=True)

    def to_dict(self):
        """Ficha completa. Solo para el panel de administración."""
        datos = self.to_dict_publico()
        datos.update({
            'dni': self.dni,
            'telefono': self.telefono,
            'email': self.email,
            'fecha_registro': _iso_utc(self.fecha_registro),
            'activo': self.activo
        })
        return datos

    def to_dict_publico(self):
        """Lo que el kiosco muestra al socio que acaba de identificarse.

        No incluye la cédula a propósito: el kiosco ya la tiene, porque el
        socio la acaba de tipear. Así el endpoint público nunca devuelve un
        documento que quien pregunta no conociera de antemano.
        """
        return {
            'id': self.id,
            'numero_socio': self.numero_socio,
            'nombre': self.nombre,
            'apellido': self.apellido,
            'nombre_completo': f"{self.apellido}, {self.nombre}"
        }
