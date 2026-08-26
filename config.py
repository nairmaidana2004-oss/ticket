"""Configuracion central del sistema de tickets.

Todos los valores sensibles o dependientes del entorno se leen de variables de
entorno. Si no estan definidas se usan valores por defecto razonables para
desarrollo local.
"""
import os
import secrets
from datetime import timedelta, timezone

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')


def _get_secret_key():
    """Clave de sesion: variable de entorno, o una generada y guardada en instance/.

    Nunca se hardcodea. El archivo generado esta en .gitignore y fuera del
    control de versiones.
    """
    key = os.environ.get('TIKETERA_SECRET_KEY')
    if key:
        return key

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    key_file = os.path.join(INSTANCE_DIR, 'secret_key.txt')

    if os.path.exists(key_file):
        with open(key_file, 'r', encoding='utf-8') as f:
            stored = f.read().strip()
            if stored:
                return stored

    generated = secrets.token_urlsafe(48)
    with open(key_file, 'w', encoding='utf-8') as f:
        f.write(generated)
    print("[CONFIG] Clave de sesion generada en instance/secret_key.txt")
    return generated


class Config:
    SECRET_KEY = _get_secret_key()

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'TIKETERA_DATABASE_URI', 'sqlite:///tickets.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Cookies de sesion
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('TIKETERA_HTTPS', '0') == '1'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # Zona horaria local (Paraguay = UTC-3). Se usa para la numeracion diaria
    # y las estadisticas, que deben seguir el dia calendario local y no UTC.
    TZ_OFFSET_HOURS = int(os.environ.get('TIKETERA_TZ_OFFSET', '-3'))

    # Llamado automatico: apagado por defecto para no pisar a los operadores.
    AUTO_CALL_ENABLED = os.environ.get('TIKETERA_AUTO_CALL', '0') == '1'
    AUTO_CALL_INTERVAL = int(os.environ.get('TIKETERA_AUTO_CALL_INTERVAL', '300'))

    # Alertas de cola: avisan ANTES de que la espera se dispare, para poder
    # abrir otra ventanilla a tiempo.
    ALERTA_ESPERA_MIN = int(os.environ.get('TIKETERA_ALERTA_ESPERA', '20'))
    ALERTA_COLA = int(os.environ.get('TIKETERA_ALERTA_COLA', '10'))

    # Horario de atencion. Fuera de el, el kiosco no emite turnos.
    # Formato: "HH:MM-HH:MM" por dia, o vacio para cerrado.
    HORARIO = {
        0: os.environ.get('TIKETERA_HORARIO_LUN', '07:00-17:00'),
        1: os.environ.get('TIKETERA_HORARIO_MAR', '07:00-17:00'),
        2: os.environ.get('TIKETERA_HORARIO_MIE', '07:00-17:00'),
        3: os.environ.get('TIKETERA_HORARIO_JUE', '07:00-17:00'),
        4: os.environ.get('TIKETERA_HORARIO_VIE', '07:00-17:00'),
        5: os.environ.get('TIKETERA_HORARIO_SAB', '07:00-12:00'),
        6: os.environ.get('TIKETERA_HORARIO_DOM', ''),
    }
    # Minutos antes del cierre en que se deja de emitir. Evita que alguien
    # saque turno para un tramite que no se va a alcanzar a atender.
    CORTE_ANTES_DEL_CIERRE = int(os.environ.get('TIKETERA_CORTE_CIERRE', '15'))
    # Con el horario apagado el sistema emite turnos a cualquier hora
    HORARIO_ACTIVO = os.environ.get('TIKETERA_HORARIO_ACTIVO', '1') == '1'

    # Origenes permitidos para CORS. Vacio = mismo origen unicamente.
    CORS_ORIGINS = [
        o.strip() for o in os.environ.get('TIKETERA_CORS_ORIGINS', '').split(',')
        if o.strip()
    ]


LOCAL_TZ = timezone(timedelta(hours=Config.TZ_OFFSET_HOURS))
