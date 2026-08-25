"""Cliente minimo de Chrome DevTools Protocol sobre WebSocket crudo.

Permite manejar el navegador de verdad (hacer clics, leer el DOM, sacar
capturas) sin instalar playwright ni selenium. Lo usa pruebas_kiosco.py.

Solo necesita la libreria estandar de Python y un navegador basado en Chromium
(Edge viene con Windows) arrancado con --remote-debugging-port.
"""
import base64
import json
import os
import socket
import struct
import urllib.request


def targets(puerto=9222):
    """Lista las pestañas abiertas en el navegador."""
    with urllib.request.urlopen(f'http://127.0.0.1:{puerto}/json') as r:
        return json.loads(r.read().decode())


class Pagina:
    """Conexion WebSocket a una pestaña del navegador."""

    def __init__(self, url):
        sin_esquema = url.split('://', 1)[1]
        hostport, _, path = sin_esquema.partition('/')
        host, _, puerto = hostport.partition(':')
        self.sock = socket.create_connection((host, int(puerto or 80)), timeout=20)

        clave = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {clave}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode())

        self.buf = b''
        while b'\r\n\r\n' not in self.buf:
            self.buf += self.sock.recv(4096)
        cabecera, _, resto = self.buf.partition(b'\r\n\r\n')
        if b'101' not in cabecera.split(b'\r\n')[0]:
            raise RuntimeError('Handshake WebSocket fallido: '
                               + cabecera.decode(errors='replace'))
        self.buf = resto
        self._id = 0

    def _leer_exacto(self, n):
        while len(self.buf) < n:
            trozo = self.sock.recv(65536)
            if not trozo:
                raise RuntimeError('conexion cerrada por el navegador')
            self.buf += trozo
        datos, self.buf = self.buf[:n], self.buf[n:]
        return datos

    def _enviar(self, texto):
        carga = texto.encode()
        largo = len(carga)
        marco = bytearray([0x81])  # FIN + texto
        if largo < 126:
            marco.append(0x80 | largo)
        elif largo < 65536:
            marco.append(0x80 | 126)
            marco += struct.pack('>H', largo)
        else:
            marco.append(0x80 | 127)
            marco += struct.pack('>Q', largo)
        mascara = os.urandom(4)  # el cliente siempre enmascara
        marco += mascara
        marco += bytes(b ^ mascara[i % 4] for i, b in enumerate(carga))
        self.sock.sendall(bytes(marco))

    def _recibir(self):
        while True:
            b1, b2 = self._leer_exacto(2)
            opcode = b1 & 0x0F
            largo = b2 & 0x7F
            if largo == 126:
                largo = struct.unpack('>H', self._leer_exacto(2))[0]
            elif largo == 127:
                largo = struct.unpack('>Q', self._leer_exacto(8))[0]
            carga = self._leer_exacto(largo)
            if opcode == 0x8:
                raise RuntimeError('el navegador cerro la conexion')
            if opcode == 0x9:  # ping -> pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if opcode in (0x1, 0x2):
                return json.loads(carga.decode('utf-8', 'replace'))

    def comando(self, metodo, **params):
        """Ejecuta un comando del protocolo y devuelve su resultado."""
        self._id += 1
        mio = self._id
        self._enviar(json.dumps({'id': mio, 'method': metodo, 'params': params}))
        while True:
            msg = self._recibir()
            if msg.get('id') == mio:
                if 'error' in msg:
                    raise RuntimeError(f"{metodo}: {msg['error']}")
                return msg.get('result', {})

    def js(self, expresion):
        """Evalua JavaScript en la pagina y devuelve el valor resultante."""
        r = self.comando('Runtime.evaluate', expression=expresion,
                         awaitPromise=True, returnByValue=True)
        if r.get('exceptionDetails'):
            det = r['exceptionDetails']
            texto = det.get('exception', {}).get('description') or det.get('text')
            raise RuntimeError('EXCEPCION JS: ' + str(texto))
        return r.get('result', {}).get('value')

    def clic_por_texto(self, selector, texto):
        """Hace clic en el primer elemento del selector cuyo texto coincida."""
        return self.js(f"""
            (() => {{
                const el = [...document.querySelectorAll({json.dumps(selector)})]
                    .find(e => e.textContent.trim() === {json.dumps(texto)});
                if (!el) return false;
                el.click();
                return true;
            }})()
        """)

    def captura(self, ruta, ancho=None, alto=None, completa=False):
        if ancho and alto:
            self.comando('Emulation.setDeviceMetricsOverride', width=ancho,
                         height=alto, deviceScaleFactor=1, mobile=False)
        datos = self.comando('Page.captureScreenshot', format='png',
                             captureBeyondViewport=completa)['data']
        os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
        with open(ruta, 'wb') as f:
            f.write(base64.b64decode(datos))
        return ruta

    def cerrar(self):
        try:
            self.sock.close()
        except OSError:
            pass


def abrir(url_pagina, puerto=9222):
    """Toma la primera pestaña del navegador y navega a la URL indicada."""
    for t in targets(puerto):
        if t.get('type') == 'page':
            p = Pagina(t['webSocketDebuggerUrl'])
            p.comando('Runtime.enable')
            p.comando('Page.enable')
            p.comando('Page.navigate', url=url_pagina)
            return p
    raise RuntimeError('no se encontro ninguna pestaña abierta en el navegador')
