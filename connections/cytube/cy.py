import importlib
import json
import os
from twisted.internet import defer
from twisted.internet.defer import Deferred
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory, \
                                       connectWS
from yukari.config import cfg
from yukari.customlogger import clog

cfg = cfg['Cytube']
syst = 'CYTUBE'

def importPlugins(path):
    path = 'connections/cytube/plugins/'
    try:
        files = os.listdir(path)
    except(OSError):
        clog.error('Plugin import error! Check that %s exists.' % path, syst)
        return []
    importPath = path.replace('/', '.')
    moduleNames = [importPath + i[:-3] for i in files
                    if not i.startswith('_') and i.endswith('.py')]
    modules = map(importlib.import_module, moduleNames)
    return modules

class CytubeProtocol(WebSocketClientProtocol):

    def __init__(self):
        modules = importPlugins('')
        self.triggers = {'commands':{},
                         'changeMedia': {}}
        for module in modules:
            instance = module.setup()
            for method in dir(instance):
                # commands in cytube chat
                if method.startswith('_com_'):
                    trigger = '$%s' % method[5:]
                    self.triggers['commands'][trigger] = getattr(instance, method)
                elif method.startswith('_cM_'):
                    self.triggers['changeMedia'][method] = getattr(instance, method)

        self.username = cfg['username']
        self.receivedChatBuffer = False


    def onOpen(self):
        # give factory a reference of this protocol instance
        self.factory.prot = self
        # tell Yukari cytube is connected
        self.factory.yuka.cyOnConnect()
        self._initialize()

    def onClose(self, wasClean, code, reason):
        clog.warning('closed protocol connection', syst)

    def onMessage(self, msg, isBinary):
        if msg == '2::':
            self.sendMessage(msg) # return heartbeat

        elif msg.startswith('5:::{'):
            fstr = msg[4:]
            fdict = json.loads(fstr)
            clog.debug(('<--%s' % fdict).decode('unicode-escape'), syst)
            self._processFrame(fdict)

    def _processFrame(self, fdict):
        name = fdict['name']
        # send to the appropriate methods
        thunk = getattr(self, '_cy_%s' % (name,), None)
        if thunk is not None:
            thunk(fdict)

    def _sendf(self, dict): # 'sendFrame' is a WebSocket method name
        frame = json.dumps(dict)
        clog.info(('-->%s' % frame).decode('unicode-escape'), syst)
        frame = '5:::' + frame
        self.sendMessage(frame)
    
    def _cy_login(self, fdict):
        if fdict['args'][0]['success']:
            self._joinRoom()
        else:
            clog.error('Login error: Check credentials.', syst)


    def _cy_chatMsg(self, fdict):
        if not self.receivedChatBuffer:
            return
        processCommand = True
        args = fdict['args'][0]
        msg = args['msg']
        username = args['username']

        # check for commands
        # avoids interpreting a relayed chat message, and also for safety
        if username != self.username and msg.startswith('$'):
            command = msg.split()[0]
            index = msg.find(' ')
            if index != -1:
                commandArgs = msg[index+1:]
            else:
                commandArgs = ''
            if command in self.triggers['commands']:
                processCommand = False
                clog.info('Command triggered:%s:%s' % (command, commandArgs),
                           syst)
                self.triggers['commands'][command](self, username, commandArgs)

        # don't resend our own messages - Cytube server echos messages
        # (note: IRC does not)
        if username != self.username:
            self.factory.yuka.relayChat(username, msg, 'cy', processCommand)

    def _cy_changeMedia(self, fdict):
        for key, method in self.triggers['changeMedia'].iteritems():
            method(self, fdict)

    # timing could change in the future
    def _cy_setMotd(self, fdict):
        self.receivedChatBuffer = True
        self.factory.yuka.cyJoined()

    def _initialize(self):
        self._sendf({'name': 'login',
                    'args': {'name': cfg['username'],
                             'pw': cfg['password']}})
    def _joinRoom(self):
        self._sendf({'name': 'joinChannel',
                     'args': {'name': cfg['channel']}})

    def sendCy(self, msg):
        self._sendf({'name': 'chatMsg', 'args': {'msg': msg}})

    def sendAll(self, msg):
        self.factory.yuka.sendAll(msg)

    def sendIrc(self, msg, action=False):
        self.factory.yuka.sendIrc(msg, action)

class CytubeFactory(WebSocketClientFactory):
    protocol = CytubeProtocol

    def clientConnectionLost(self, connector, reason):
        clog.warning('Client Connection Lost %s, %s' % (connector, reason),
                      syst)

    def clientConnectionFailed(self, connector, reason):
        clog.warning('Client Connection Failed %s, %s' % (connector, reason),
                     syst)

def startConnection(sid):
    domain = cfg['domain']
    port = cfg['port']
    wsurl = 'ws://%s:%s/socket.io/1/websocket/%s/' % (domain, port, sid)
    clog.info('WS url: %s' % wsurl, syst)
    cytubeFactory = CytubeFactory(wsurl)
    connectWS(cytubeFactory)
    return cytubeFactory

