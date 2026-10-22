"""iAP2 carried inside AirPlay iAPSendMessage commands.

After the Wi-Fi handover some head units drop Bluetooth and restart iAP2
inside the AirPlay session: they send iAPSendMessage events whose
params['data'] holds raw iAP2 link bytes (starting with the detect
sequence), and expect the phone to answer with iAPSendMessage commands.

IAPTunnel gives the link code an ordinary socket. Bytes from the head unit
are written into one end of a socket pair; whatever the link code writes
comes out of the other end and is handed to send().
"""
import socket
import threading


def tunnel_payload(value):
    """Return the iAP2 bytes of an iAPSendMessage plist, or None."""
    params = value.get('params') if isinstance(value, dict) else None
    data = params.get('data') if isinstance(params, dict) else None
    return bytes(data) if isinstance(data, (bytes, bytearray)) and data else None


class IAPTunnel:
    def __init__(self, run_link, send, max_starts=30):
        # run_link(sock, stop) runs one iAP2 link and returns when it ends.
        self.run_link, self.send, self.max_starts = run_link, send, max_starts
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.starts = 0
        self.local = None
        self.link = None
        self.link_stop = None

    def feed(self, data):
        """Pass head-unit bytes to the link, starting a fresh link if needed."""
        with self.lock:
            if self.stop.is_set():
                return False
            if self.link is None or not self.link.is_alive():
                if not self._start():
                    return False
            try:
                self.local.sendall(data)
            except OSError:
                return False
            return True

    def _start(self):
        if self.starts >= self.max_starts:
            if self.starts == self.max_starts:
                print('iAP tunnel: link restart limit reached', flush=True)
                self.starts += 1
            return False
        self.starts += 1
        if self.local:
            self.local.close()
        self.local, remote = socket.socketpair()
        self.link_stop = threading.Event()
        self.link = threading.Thread(target=self._run, args=(remote, self.link_stop), daemon=True,
                                     name='iAP tunnel link {}'.format(self.starts))
        threading.Thread(target=self._pump, args=(self.local,), daemon=True).start()
        self.link.start()
        print('iAP tunnel: link started (attempt {})'.format(self.starts), flush=True)
        return True

    def _run(self, remote, link_stop):
        try:
            self.run_link(remote, link_stop)
        except Exception as error:
            print('iAP tunnel: link failed: {}'.format(type(error).__name__), flush=True)
        finally:
            remote.close()

    def _pump(self, local):
        while True:
            try:
                data = local.recv(4096)
            except OSError:
                return
            if not data:
                return
            self.send(data)

    def close(self):
        with self.lock:
            self.stop.set()
            if self.link_stop:
                self.link_stop.set()
            if self.local:
                try:
                    self.local.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.local.close()
