import importlib
import json
import os
from twisted.internet import defer
from twisted.internet.defer import Deferred
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory, \
                                       connectWS
from connections.database import db
from yukari.config import cfg
from yukari.customlogger import clog
from yukari.tools import getTime

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

        self.userdict = {}
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
    
    def _cy_addUser(self, fdict):
        user = fdict['args'][0]
        timeNow = getTime()
        if user['name'] not in self.userdict:
            self._userJoin(user, timeNow)
            clog.info('Added %s to userdict' % user['name'], syst)
        else:
            clog.error('A user in userdict joined!' % user['name'], syst)

    def _cy_changeMedia(self, fdict):
        for key, method in self.triggers['changeMedia'].iteritems():
            method(self, fdict)

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
        if username != self.username and username != '[server]':
            self.factory.yuka.relayChat(username, msg, 'cy', processCommand)

    def _cy_login(self, fdict):
        if fdict['args'][0]['success']:
            self._joinRoom()
        else:
            clog.error('Login error: Check credentials.', syst)

    # timing could change in the future
    def _cy_setMotd(self, fdict):
        self.receivedChatBuffer = True
        self.factory.yuka.cyJoined()

    def _cy_userLeave(self, fdict):
        timeNow = getTime()
        username = fdict['args'][0]['name']
        if not username:
            return
        leftUser = self.userdict.pop(username, None)
        if leftUser:
            clog.info('%s has been removed from userdict.' % leftUser['name'],
                        syst)
            _dbLogoutUser(leftUser, timeNow)
        else:
            clog.error('A user not in userdict has left (%s) !' %
                        leftUser['name'], syst)

    def _cy_usercount(self, fdict):
        usercount = fdict['args'][0]
        self.usercount = usercount
        anoncount = usercount - len(self.userdict)
        _dbUsercount(usercount, anoncount, getTime())

    def _cy_userlist(self, fdict):
        self.userdict = {}
        userlist = fdict['args'][0]
        timeNow = getTime()
        for user in userlist:
           self._userJoin(user, timeNow)

    def _initialize(self):
        self._sendf({'name': 'login',
                    'args': {'name': cfg['username'],
                             'pw': cfg['password']}})

    def _joinRoom(self):
        self._sendf({'name': 'joinChannel',
                     'args': {'name': cfg['channel']}})

    def _userJoin(self, user, timeNow):
        self.userdict[user['name']] = user
        self.userdict[user['name']]['joined'] = timeNow
        self.userdict[user['name']]['keyId'] = None
        d = _returnKeyId(user, timeNow)
        d.addCallback(self._cbSetUserKeyId, user['name'])
        # keep a reference of deferred in each user value, so database
        # operations can be chained while the 'keyId' is being retrieved
        self.userdict[user['name']]['deferred'] = d

    def _cbSetUserKeyId(self, keyId, username):
        if not keyId:
            clog.error('Could not retrieve or add user %s for keyId!' %
                       username, syst)
            return
        keyId = str(keyId)
        clog.info('Obtained keyId for %s, KeyId: %s' % (username, keyId), syst)
        self.userdict[username]['keyId'] = keyId
        return keyId

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

# databse CyUser
def _returnKeyId(user, timeNow):
    """ Retrieve user's keyId if exists, or
        enter a new row and return keyId """
    d = _lookupUserId(user)
    d.addCallback(_checkUserId, user, timeNow)
    return d

def _lookupUserId(user):
    sql = 'SELECT userId FROM CyUser WHERE nameLower=? AND registered=?'
    isRegistered = 1 if user['rank'] else 0
    binds = (user['name'].lower(), isRegistered)
    return db.query(sql, binds)

def _checkUserId(result, user, timeNow):
    if result:
        return result[0][0]
    # no row found. Need to add as new user
    else:
        return _dbAddNewCyUser(user, timeNow)

def _dbAddNewCyUser(user, timeNow):
    isRegistered = 1 if user['rank'] else 0
    values = (None, user['name'].lower(), isRegistered, user['name'], 0, 0,
             user['profile']['text'], user['profile']['image'])
    clog.info('Inserting new row for %s.' % user['name'], syst)
    return db.insertRetLastRow('CyUser', *values)

# database UserInOut
def _dbLogoutUser(user, timeNow):
    if user['keyId']:
        _dbLogUserTime(user['keyId'], user, timeNow)
    else:
        user['deferred'].addCallback(_dbLogUserTime, user, timeNow)

def _dbLogUserTime(keyId, user, timeNow):
    sql = 'INSERT INTO UserInOut VALUES (?, ?, ?, ?)'
    values = (keyId, user['joined'], timeNow, 0)
    db.operate(sql, values)
    return keyId

# database usercount
def _dbUsercount(usercount, anoncount, timeNow):
    sql = 'INSERT INTO Usercount VALUES (?, ?, ?)'
    values = (timeNow, usercount, anoncount)
    db.operate(sql, values)

