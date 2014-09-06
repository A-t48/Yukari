import importlib
import os
from connections.cytube import cy, getSid, parser
from connections.irc import ircc
from connections.telnet import telnetc
from yukari.customlogger import clog
from yukari.config import cfg

syst = 'YUKARI'
def importPlugins(path):
    try:
        files = os.listdir(path)
    except(OSError):
        clog.error('Error importing', syst)
        return []
    importPath = path.replace('/', '.')
    moduleNames = [importPath + i[:-3] for i in files
                    if not i.startswith('_') and i.endswith('.py')]
    modules = map(importlib.import_module, moduleNames)
    return modules

class Yukari(object):

    def __init__(self):
        # import plugins
        self._importPlugins()
        # connections (if connected to the server)
        self.cyc = False
        self.ircc = False
        # online (if in room/channel and ready to relay chat and take commands)
        self.cy = False
        self.irc = False
        # start the connections
        self.connectCytube()
        self.connectIrc()
        self.connectTelnet()
        clog.debug('debug', 'DEBUG')
        clog.info('info', 'INFO')
        clog.warning('warning', 'WARNING')
        clog.error('error', 'ERROR')
        clog.critical('critical', 'CRITICAL')


    def _importPlugins(self):
        modules = importPlugins('yukari/plugins/')
        self.triggers = {'commands':{}}
        for module in modules:
            instance = module.setup()
            for method in dir(instance):
                # commands in cytube chat
                if method.startswith('_com_'):
                    trigger = '$%s' % method[5:]
                    self.triggers['commands'][trigger] = getattr(instance, method)
                    clog.info('Imported %s!' % trigger, syst)

    def connectCytube(self):
        d = getSid.retreiveSid(cy.startConnection)
        d.addCallback(self.cySetFactory)

    def cySetFactory(self, factory):
        self.cytubeFactory = factory
        # give factory a reference of Yukari instance
        self.cytubeFactory.yuka = self

    def cyOnConnect(self):
        self.cyc = True
        clog.info('Yukari connected to Cytube', syst)

    def cyJoined(self):
        self.cy = True
        clog.info('Yukari joined the cytube channel', syst)

    def connectIrc(self):
        from twisted.internet import reactor
        self.ircFactory = ircc.startConnection()
        # give factory a reference of Yukari instance
        self.ircFactory.yuka = self
        reactor.connectTCP(cfg['irc']['uri'], int(cfg['irc']['port']),
                                                     self.ircFactory)

    def ircConnectionMade(self):
        self.ircc = True
        clog.info('Yukari connected to IRC network', syst)

    def ircJoined(self, channel):
        self.irc = True
        clog.info('Yukari joined %s' % channel, syst)

    def connectTelnet(self):
        clog.debug('Starting telnet service', syst)
        telnetc.createShellServer(self)

    def relayChat(self, username, msg, origin, processCommand=True, opts=None):
        if opts is None:
            opts = {}
        if origin == 'cy':
            clog.debug(msg, syst)
            msg = parser.stripTags(msg)
        if origin != 'cy' and self.cy:
            relay = '(%s) %s' % (username, msg)
            self.cytubeFactory.prot.sendCy(relay)
        if origin != 'irc' and self.irc:
            relay = '(%s) %s' % (username, msg)
            self.ircFactory.prot.sendIrc(relay)
        if processCommand and msg.startswith('$'):
            command = msg.split()[0]
            index = msg.find(' ')
            if index != -1:
                commandArgs = msg[index+1:]
            else:
                commandArgs = ''
            if command in self.triggers['commands']:
                clog.debug('triggered command: [%s] args:[%s]' % 
                           (command, commandArgs), syst)
                self.triggers['commands'][command](self, username, commandArgs)

    def sendAll(self, message):
        self.cytubeFactory.prot.sendCy(message)
        self.ircFactory.prot.sendIrc(message)

    def sendIrc(self, message, action=False):
        self.ircFactory.prot.sendIrc(message, action)

def start():
    y = Yukari()
    from twisted.internet import reactor
    reactor.run()
