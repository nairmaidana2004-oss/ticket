"""Arranque del sistema con servidor de produccion (waitress).

El servidor de desarrollo de Flask no esta pensado para uso real: no maneja
bien varias conexiones simultaneas ni se recupera de errores. Waitress si, y
funciona nativo en Windows.

    python iniciar.py

Variables de entorno utiles:
    TIKETERA_PORT             puerto (default 5000)
    TIKETERA_SECRET_KEY       clave de sesion (si no, se genera en instance/)
    TIKETERA_TZ_OFFSET        zona horaria, default -3 (Paraguay)
    TIKETERA_AUTO_CALL        '1' para activar el llamado automatico
    TIKETERA_ADMIN_PASSWORD   solo la usa init_db.py
"""
import os
import sys
import threading

from app import _avisar_credenciales_por_defecto, app, auto_caller_worker

try:
    from waitress import serve
except ImportError:
    print("[ERROR] Falta la dependencia 'waitress'. Instalela con:")
    print("        pip install -r requirements.txt")
    print("\n        (Para una prueba rapida sin waitress: python app.py)")
    sys.exit(1)


def main():
    puerto = int(os.environ.get('TIKETERA_PORT', '5000'))

    with app.app_context():
        _avisar_credenciales_por_defecto()

    if app.config['AUTO_CALL_ENABLED']:
        threading.Thread(
            target=auto_caller_worker, name='AutoCallerThread', daemon=True
        ).start()
        print(f"Llamado automatico ACTIVO cada {app.config['AUTO_CALL_INTERVAL']}s")
    else:
        print("Llamado automatico desactivado (TIKETERA_AUTO_CALL=1 para activarlo)")

    print("=" * 58)
    print("  SISTEMA DE TICKETS - COOPERATIVA REDUCTO LTDA.")
    print("=" * 58)
    print(f"  Kiosco (entrada) .... http://localhost:{puerto}/")
    print(f"  Sala de espera (TV) . http://localhost:{puerto}/sala_espera")
    print(f"  Panel operador ...... http://localhost:{puerto}/operador")
    print(f"  Administracion ...... http://localhost:{puerto}/admin")
    print("=" * 58, flush=True)

    serve(app, host='0.0.0.0', port=puerto, threads=8)


if __name__ == '__main__':
    main()
