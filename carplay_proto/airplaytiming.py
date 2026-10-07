"""Peer-restricted RTCP timing responder for AirPlay session bootstrap."""
import socket
import struct
import threading
import time


def timing_response(request, received_ns, sent_ns):
    if len(request) != 32 or request[1] != 0xd2:
        return None
    def ntp(nanos):
        seconds, fraction = divmod(nanos, 1000000000)
        return ((seconds & 0xffffffff) << 32) | (fraction << 32) // 1000000000
    return b'\x80\xd3\x00\x07' + request[4:8] + request[24:32] + struct.pack('>QQ',ntp(received_ns),ntp(sent_ns))


class TimingServer:
    def __init__(self, tcp_socket):
        self.peer = tcp_socket.getpeername()[0]
        local = list(tcp_socket.getsockname())
        local[1] = 0
        self.sock = socket.socket(tcp_socket.family, socket.SOCK_DGRAM)
        self.sock.bind(tuple(local))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                request, peer = self.sock.recvfrom(256)
                received = time.monotonic_ns()
                if peer[0] == self.peer:
                    response = timing_response(request, received, time.monotonic_ns())
                    if response is not None:
                        self.sock.sendto(response,peer)
            except socket.timeout:
                pass
            except OSError:
                return

    def close(self):
        self.stop.set()
        self.thread.join(0.5)
        self.sock.close()
