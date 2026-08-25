import os

import paramiko

# Las claves privadas viven fuera del proyecto (nunca dentro de OneDrive/git).
# Se pueden sobrescribir con variables de entorno.
KEY_PATH = os.environ.get(
    'TIKETERA_SSH_KEY',
    os.path.join(os.path.expanduser('~'), '.ssh', 'id_rsa_192_168_10_120')
)
REMOTE_HOST = os.environ.get('TIKETERA_SSH_HOST', '192.168.10.120')
REMOTE_USER = os.environ.get('TIKETERA_SSH_USER', 'root')
KNOWN_HOSTS = os.path.join(os.path.expanduser('~'), '.ssh', 'known_hosts')


def run_remote_command(command):
    """
    Ejecuta un comando en el servidor remoto usando la clave SSH.
    Retorna (stdout, stderr) como strings.
    """
    if not os.path.exists(KEY_PATH):
        raise FileNotFoundError(f"Clave SSH no encontrada en {KEY_PATH}")

    client = paramiko.SSHClient()
    # RejectPolicy: no aceptamos hosts desconocidos en silencio.
    # Para dar de alta el host la primera vez:
    #   ssh-keyscan 192.168.10.120 >> ~/.ssh/known_hosts
    client.load_system_host_keys()
    if os.path.exists(KNOWN_HOSTS):
        client.load_host_keys(KNOWN_HOSTS)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    try:
        key = paramiko.RSAKey.from_private_key_file(KEY_PATH)
        client.connect(REMOTE_HOST, username=REMOTE_USER, pkey=key, timeout=5)

        stdin, stdout, stderr = client.exec_command(command)
        out = stdout.read().decode('utf-8')
        err = stderr.read().decode('utf-8')

        return out, err
    except Exception as e:
        return None, str(e)
    finally:
        client.close()


if __name__ == "__main__":
    print("Probando conexion remota...")
    out, err = run_remote_command("uptime")
    if err:
        print("Error:", err)
    else:
        print("OK. Uptime:", out)
