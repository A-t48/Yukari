import database, apiClient, tools
from tools import clog
from conf import config
import json, time, re
from collections import deque
from sqlite3 import IntegrityError
from twisted.python.util import InsensitiveDict
from twisted.internet import reactor, defer
from twisted.internet.error import AlreadyCalled, AlreadyCancelled
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory

sys = 'CytubeClient'
class NoRowException(Exception):
    pass

class CyProtocol(WebSocketClientProtocol):

    def __init__(self):
        self.unloggedChat = []
        self.lastChatLogTime = 0
        self.testan = ''
        self.receivedChatBuffer = False
        ### Need to imporve this regex, it matches non-videos
        # ie https://www.youtube.com/feed/subscriptions
        self.ytUrl = re.compile(
                (r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.'
                  '(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'))

    def onOpen(self):
        clog.info('(onOpen) Connected to Cytube!', sys)
        self.connectedTime = time.time()
        self.lastUserlist = 0
        self.factory.prot = self
        self.factory.handle.cy = True
        self.initialize()

    def onMessage(self, msg, binary):
        if msg == '2::':
            self.sendMessage(msg) # return heartbeat
        elif msg.startswith('5:::{'):
            fstr = msg[4:]
            fdict = json.loads(fstr)
            #if fdict['name'] in ('chatMsg', 'userlist', 'addUser', 'userLeave'):
                #print fstr
            self.processFrame(fdict)

    def onClose(self, wasClean, code, reason):
        clog.info('(onClose) Closed Protocol connection: %s' % reason, sys)

    def sendf(self, dict): # 'sendFrame' is a WebSocket method name
        frame = json.dumps(dict)
        frame = '5:::' + frame
        clog.debug('(sendf) [->] %s' % frame, sys)
        self.sendMessage(frame)

    def sendChat(self, msg, modflair=False):
        if modflair:
            modflair = 3 ### TODO remove hardcode rank
        self.sendf({'name': 'chatMsg',
                   'args': {'msg': msg, 'meta': {'modflair': modflair}}})

    def initialize(self):
        self.sendf({'name': 'initChannelCallbacks'})
        name = config['Cytube']['username']
        pw = config['Cytube']['password']
        self.sendf({'name': 'login',
                    'args': {'name': name, 'pw': pw}})

    def processFrame(self, fdict):
        name = fdict['name']
        # send to the appropriate methods
        thunk = getattr(self, '_cyCall_%s' % (name,), None)
        if thunk is not None:
            thunk(fdict)
        else:
            pass
            #print 'No method defined for %s.' % name

    def joinRoom(self):
        channel = config['Cytube']['channel']
        self.sendf({'name': 'joinChannel', 'args': {'name':channel}})

    def searchYoutube(self, msg):
        m = self.ytUrl.search(msg)
        if m:
            ytId = m.group(6)
            clog.debug('(searchYoutube) matched: %s' % ytId, sys)
            d = apiClient.requestApi(ytId)
            d.addCallbacks(self.sendChat, self.errYtInfo)

    def _cyCall_login(self, fdict):
        if fdict['args'][0]['success']:
            self.joinRoom()

    def _cyCall_setMotd(self, fdict):
        # setMotd comes after the chat buffer when joining a channel
        self.receivedChatBuffer = True

    def _cyCall_chatMsg(self, fdict):
        if not self.receivedChatBuffer:
            return
        args = fdict['args'][0]
        timeNow = round(time.time(), 2)
        username = args['username']
        msg = args['msg']
        chatCyTime = round((args['time'])/1000.0, 2)
        if 'modflair' in args['meta']:
            modflair = args['meta']['modflair']
        else:
            modflair = None
        #print username
        if username in self.userdict or username == '[server]':
            if username == '[server]':
                keyId = 2
            else:
                keyId = self.userdict[username]['keyId']
            #print '%s has id %s, says %s' % (username, keyId, msg)
            if keyId:
                self.unloggedChat.append((None, keyId, timeNow, chatCyTime, msg,
                                          modflair, 0))
                if time.time() - self.lastChatLogTime < 3:
                    self.cancelChatLog()
                    self.dChat = reactor.callLater(3, self.bulkLogChat,
                                                   self.unloggedChat)
                else:
                    self.cancelChatLog()
                    self.bulkLogChat(self.unloggedChat)
                    self.lastChatLogTime = time.time()
            else:
                assert keyId is None
                chatArgs = (timeNow, chatCyTime, msg, modflair, 0)
                self.userdict[username]['deferred'].addCallback(self.deferredChat,
                                                                chatArgs)
                
            if username != config['Cytube']['username'] and username != '[server]':
                # comment line below for test. #TODO make proper test
                self.factory.handle.recCyMsg(username, msg)
                self.searchYoutube(msg)

    def cancelChatLog(self):
        try:
            self.dChat.cancel()
            clog.debug('(cancelChatLog) Cancelled log timer', sys)
        except AttributeError as e:
            clog.debug('(cancelChatLog): %s' % e, sys)
        except AlreadyCancelled as e:
            clog.debug('(cancelChatLog): %s' % e, sys)
        except AlreadyCalled as e:
            clog.debug('(cancelChatLog): %s' % e, sys)
        except NameError as e:
            clog.error('(cancelChatLog): %s' % e, sys)

    def bulkLogChat(self, chatlist):
        assert self.unloggedChat == chatlist
        self.unloggedChat = []
        #print 'Logging %s !!' % chatlist
        return database.bulkLogChat('cyChat', chatlist)

    def deferredChat(self, res, chatArgs):
        """ Logs chat to database. Since this will be added to the userAdd
        deferred chain, we ensure that the user is given a keyId before database
        insert. This will rarely be triggered since a user must join and
        immediatly chat before they are queried or written to the user database.
        res is the key id from lastrowid or itself"""
        keyId = res
        dd = database.insertChat(None, keyId, *chatArgs)
        # this inner deferred ensures that the outer deferred's response
        # is always a keyId, in case we need to keep chaining more chat log
        # callbacks.
        dd.addCallback(self.deferredChatRes, keyId)

    def deferredChatRes(self, res, key):
        if not res:
            clog.info('(deferredChatRes): wrote chat to database!', sys)
            return defer.succeed(key)
        else:
            clog.err('(deferredChatRes): error writing to database!', sys)
            return defer.fail(key)

    def _cyCall_addUser(self, fdict):
        user = fdict['args'][0]
        timeNow = int(time.time())
        if user['name'] not in self.userdict:
            self.userJoin(user, timeNow)
        self.userdict[user['name']]['inChannel'] = True

    def userJoin(self, user, timeNow):
        user['keyId'] = None
        user['timeJoined'] = timeNow
        self.userdict[user['name']] = user
        reg = self.checkRegistered(user['name'])
        d = database.dbQuery(('userId', 'flag', 'lastSeen'), 'cyUser',
                         nameLower=user['name'].lower(), registered=reg)
        d.addCallback(database.queryResult)
        values = (None, user['name'].lower(), reg, user['name'], 0, 0,
                 timeNow, timeNow, 0)
        d.addErrback(database.dbInsertReturnLastRow, 'cyUser', *values)
        d.addCallback(self.cacheKey, user)
        # add a reference to the deferred to the userdict
        self.userdict[user['name']]['deferred'] = d
        
    def cacheKey(self, res, user):
        assert res, 'no res at cacheKey'
        if res:
            clog.info("(cacheKey) cached %s's key %s" % (user['name'], res[0]),
                      sys)
            self.userdict[user['name']]['keyId'] = res[0]

    def _cyCall_userLeave(self, fdict):
        username = fdict['args'][0]['name']
        self.userdict[username]['inChannel'] = False
        d = self.userdict[username]['deferred']
        clog.debug('_cyCall_userLeave) user %s has left. Adding callbacks' 
                   % username, sys)
        leftUser = self.userdict[username]
        d.addCallback(self.clockUser, leftUser,
                      int(time.time()))
        d.addErrback(self.dbErr)
        d.addCallback(self.removeUser, username)
        d.addErrback(self.dbErr)

    def removeUser(self, res, username):
        clog.debug('(removeUser) Removing user', sys)
        try:
            if not self.userdict[username]['inChannel']:
                del self.userdict[username]
                clog.debug('(removeUser) deleted %s' % username, sys)
            else:
                clog.error('(removeUser) skipping: user %s in channel' % username, sys)
        except(KeyError):
            clog.error('(removeUser) Failed: user %s not in userdict' % username, sys)
            return KeyError

    def _cyCall_userlist(self, fdict):
        if time.time() - self.lastUserlist < 3: # most likely the same userlist
            clog.info('(_cy_userlist) Duplicate userlist detected', sys) # but with ip/aliases if mod+
            return
        self.lastUserlist = time.time()
        userlist = fdict['args'][0]
        timeNow = int(time.time())

        # make a dictonary of users
        self.userdict = {}
        for user in userlist:
            user['timeJoined'] = timeNow
            self.userdict[user['name']] = user
            self.userJoin(user, timeNow)


    def queryUserId(self, username, isRegistered):
        """ Query UserId to log chat to database """
        sql = 'SELECT userId FROM cyUser WHERE nameLower=? AND registered=?'
        binds = (username.lower()+self.testan, isRegistered)
        return database.query(sql, binds)
    
    def errYtInfo(self, err):
        clog.error('(errYtInfo) %s' % err, sys)

    def dbErr(self, err):
        clog.error('(dbErr): %s' % err.value, sys)

    def cleanUp(self):
        # set restart to False
        self.factory.handle.cyRestart = False
        # disconnect first so we don't get any more join/leaves
        self.sendClose()
        # log everyone's access time before shutting down
        timeNow = int(time.time())
        for name, user in self.userdict.iteritems():
            user['deferred'].addCallback(self.clockUser, user, timeNow)
        self.cyRestart = False

    def clockUser(self, res, leftUser, timeNow):
        """ Clock out a user, by updating their accessTime """
        username = leftUser['name']
        clog.info('(clockUser) Clocking out %s!' % username, sys)
        timeJoined = leftUser['timeJoined']
        timeStayed = timeNow - timeJoined
        userId = leftUser['keyId']
        return database.updateCyUser(timeNow, timeStayed, userId)

    def checkRegistered(self, username):
        """ Return wether a Cytube user is registered (1) or a guest (0) given
        a username. Checks self.userdict for rank information."""
        if username == '[server]':
            return 1
        else:
            try:
                user = self.userdict[username]
            except KeyError as e:
                clog.error('(checkRegistered): %s' % e, sys)
                #raise
            if user['rank'] == 0:
                return 0
            else:
                return 1

class WsFactory(WebSocketClientFactory):
    protocol = CyProtocol

    def __init__(self, arg):
        WebSocketClientFactory.__init__(self, arg)

    def clientConnectionLost(self, connector, reason):
        clog.warning('(clientConnectionLost) Connection lost to Cyutbe. %s' % reason, sys)
        if not self.handle.cyRestart:
            self.handle.doneCleanup('cy')
        else:
            #self.handle.cyPost() # reconnect
            self.handle.doneCleanup('cy')

    def clientConnectionFailed(self, connector, reason):
        clog.error('(clientConnectionFailed) Connection failed to Cytube. %s' % reason, sys)
