from twisted.manhole import telnet
from yukari.config import cfg

cfg = cfg['telnet']

def createShellServer(yukari):
    """
    Creates an interactive shell interface to send and receive output
    while the program is running. The Connection's instance yukari is 
    named y.
    e.g. dir(y) will list all of yukari's names.
    """
    factory = telnet.ShellFactory()
    from twisted.internet import reactor
    server = reactor.listenTCP(int(cfg['port']), factory)
    factory.namespace['y'] = yukari
    factory.username = cfg['username']
    factory.password = cfg['password']
    return server
