import socket
import os

apikey = os.environ.get('HOSTEDGRAPHITE_APIKEY')
if apikey:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def metrics(name: str, value) -> None:
    if apikey:
        sock.sendto(f"{apikey}.{name} {value}\n", ("carbon.hostedgraphite.com", 2003))
