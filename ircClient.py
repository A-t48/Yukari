import database
import time
import tools
from tools import clog
from tools import getTime
from conf import config
from collections import deque
from twisted.words.protocols import irc
from twisted.internet import reactor, defer, task
from twisted.internet.protocol import ClientFactory

# on Rizon networks, the optional part/quit message rarely works.
class NoRowException(Exception):
    pass

sys = 'IrcClient'
class IrcProtocol(irc.IRCClient):
    lineRate = None # use our own throttle methods
    nickname = str(config['irc']['nick'])
    heartbeatInterval = 30

    def __init__(self):
        # collect all LoopingCall's and callLater's
        self.loops = []
        self.laters = []
        self.onlineNick = str(config['irc']['nick'])
        self.offlineNick = str(config['irc']['offlinenick'])
        self.channelName = str(config['irc']['channel'])
        self.channelNp = str(config['irc']['np'])
        if not self.channelName.startswith('#'):
            self.channelName = '#' + self.channelName
        if not self.channelNp.startswith('#'):
            self.channelNp = '#' + self.channelNp
        self.chatQueue = deque()
        self.bucketToken = int(config['irc']['bucket'])
        self.bucketTokenMax = int(config['irc']['bucket'])
        self.throttleLoop = task.LoopingCall(self.addToken)
        self.loops.append(self.throttleLoop)
        self.underSpam = False
        self.nickdict = {} # {('nick','user','host'): id}
        self.nicklist = []
        self.ircConnect = time.time()
        self._namescallback = {}
        self.checkServerLoop = task.LoopingCall(self.checkServer)
        self.loops.append(self.checkServerLoop)
        self.lastPong = 0

    def checkServer(self):
        """ Tests periodically if the last PONG from the server was
            recent. Otherwise, treats it as a disconnect, and quits the
            connection. """
        pongAgo = round(time.time() - self.lastPong, 3)
        #clog.info('(checkServer) %d seconds since last PONG' % pongAgo, sys)
        if time.time() - self.lastPong > 35:
            clog.warning('No PONG response for over 35 seconds!', sys)
            self.quit(message='No server response...')

    def irc_PONG(self, server, payload):
        #clog.info('PONG reply %s: %s' % (server, payload), sys)
        self.lastPong = time.time()

    def pong(self, user, secs):
        """
        Called with the results of a CTCP PING query.
        """
        clog.info('PONG %s: %s secs' % (user, secs), sys)

    def _addQueue(self, msg, action):
        if not self.underSpam and self.bucketToken != 0:
            self.chatQueue.append((msg, action))
            self.popQueue()
        elif self.underSpam:
            clog.info('(_addQueue) chat is throttled', sys)
            return

        elif self.bucketToken == 0:
            clog.warning('(_addQueue) blocking messages from CyTube', sys)
            msg = '[Hit throttle: Dropping messages %s.]'
            self.say(self.channelName, msg % 'from Cytube')
            self.factory.handle.sendToCy(msg % 'to IRC', modflair=True)
            self.underSpam = True

    def addToken(self):
        if self.bucketToken < self.bucketTokenMax:
            clog.debug('(addToken) +1, token: %s' % self.bucketToken, sys)
            self.bucketToken += 1
        if self.underSpam and self.bucketToken > 10:
            self.underSpam = False
            self.say(self.channelName, 
                    '[Resuming relay from Cytube.]')
            self.factory.handle.sendToCy('[Resuming relay to IRC.]',
                                  modflair=True)
        elif self.bucketToken == self.bucketTokenMax:
            self.throttleLoop.stop()

    def popQueue(self):
        clog.debug('(popQueue) sending chat from IRC chat queue', sys)
        self.bucketToken -= 1
        msg, action = self.chatQueue.popleft()
        self.logSay(self.channelName, msg, action)
        if not self.throttleLoop.running:
            self.throttleLoop.start(2, now=False)

    def logSay(self, channel, msg, action):
        """ Log and send out message """
        sql = 'INSERT INTO IrcChat VALUES(?, ?, ?, ?, ?, ?)'
        msgd = msg.decode('utf-8')
        # flag 1 = Yukari sent (0 for receive)
        # flag 3 = Yukari sent + action (2 for action)
        flag = 1 if not action else 3
        binds = (None, 1, 3, getTime(), msgd, flag)
        d = database.operate(sql, binds) # must be in unicode
        if not action:
            self.say(channel, msg) # must not be in unicode
        else:
            self.describe(channel, msg)
        
    def sayNowPlaying(self, msg):
        if self.channelNp:
            self.say(self.channelNp, msg)

    def getNicks(self, channel):
        channel = channel.lower()
        d = defer.Deferred()
        if channel not in self._namescallback:
            self._namescallback[channel] = ([], [])

        self._namescallback[channel][0].append(d)
        self.sendLine('NAMES %s' % channel)
        return d

    def irc_RPL_NAMREPLY(self, prefix, params):
        channel = params[2].lower()
        nicklist = params[3].split(' ')
        if channel not in self._namescallback:
            return
        
        n = self._namescallback[channel][1]
        n += nicklist

        clog.debug('(irc_RPL_NAMREPLY) nicklist:%s' % nicklist, sys)
        if channel == self.channelName:
            self.nicklist = nicklist

    def irc_RPL_ENDOFNAMES(self, prefix, params):
        channel = params[1].lower()
        if channel not in self._namescallback:
            return

        callbacks, namelist = self._namescallback[channel]
        for cb in callbacks:
            cb.callback(namelist)

        del self._namescallback[channel]

        clog.debug('(irc_RPL_ENDOFNAMES) prefix::%s, params %s.' 
                    % (prefix, params), sys)

    def updateNicks(self, namelist, channel):
        if channel != self.channelName:
            return
        # assume @ users are bots (not entierly accurate)
        users = [u for u in namelist if not u.startswith('&')]
        self.factory.handle.ircUserCount = len(users)

    def setOnlineNick(self):
        """ Sets nick for when Cytube is offline """
        self.setNick(self.onlineNick)

    def setOfflineNick(self):
        """ Sets nick for when Cytube is offline """
        self.setNick(self.offlineNick)

    def setInitialNick(self):
        clog.warning('(setInitialNick) setting initial nickname', sys)
        if self.factory.handle.cy:
            self.setOnlineNick()
        else:
            self.setOfflineNick()

    def connectionMade(self):
        # since we overwrote the method
        irc.IRCClient.connectionMade(self)

    def signedOn(self):
        self.identify()
        # wait 1 second to finish identifying
        # not really important, but joining before ident won't show the VHOST :)
        # For some reason I don't get a privmsg reply from NickServ, it might be
        # a special callback...
        self.laters.append(reactor.callLater(0.9, self.setInitialNick))
        self.laters.append(reactor.callLater(1, self.join, self.channelName))
        if self.channelNp:
            self.laters.append(reactor.callLater(1, self.join, self.channelNp))
        self.factory.prot = self
        # send an initial ping
        self.sendLine('PING 0')
        self.laters.append(reactor.callLater(10, self.checkServerLoop.start,
                                              30, now=True))

    def identify(self):
        self.msg('NickServ', 'IDENTIFY %s' % str(config['irc']['pass']))

    def userJoined(self, user, channel):
        clog.info('%s has joined %s' % (user, channel), sys)
        if channel == self.channelName:
            self.factory.handle.ircUserCount += 1
            self.nicklist.append(user)

    def userLeft(self, user, channel):
        clog.info('%s has left %s' % (user, channel), sys)
        if channel == self.channelName:
            self.factory.handle.ircUserCount -= 1
            try:
                self.nicklist.remove(user)
            except(ValueError):
                clog.error('(userLeft) User %s not in nicklist' % user)

    def userQuit(self, user, channel):
        # channel is not specified on quit
        clog.info('%s has quit %s' % (user, channel), sys)
        if user in self.nicklist:
            self.nicklist.remove(user)
            self.factory.handle.ircUserCount -= 1

    def userKicked(self, kickee, channel, kicker, message):
        clog.info('%s was kicked by %s from %s: %s' %
                  (kickee, kicker, channel, message))
        if channel == self.channelName:
            self.factory.handle.ircUserCount -= 1
            try:
                self.nicklist.remove(kickee)
            except(ValueError):
                clog.error('(userKiced) User %s not in nicklist' % kickee)
        
    def userRenamed(self, oldname, newname):
        clog.info('%s is now known as %s' % (oldname, newname), sys)

    def nickChanaged(self, nick):
        self.nickname = nick

    def joined(self, channel):
        clog.info('Joined IRC channel: %s' % channel, sys)
        self.factory.handle.irc = True
        if channel == self.channelName:
            self.factory.handle.inIrcChan = True
        elif channel == self.channelNp:
            self.factory.handle.inIrcNp = True
        self.getNicks(channel).addCallback(self.updateNicks, channel)

    def left(self, channel):
        clog.info('Left IRC channel: %s' % channel, sys)
        if channel == config['irc']['channel']:
            self.factory.handle.inIrcChan = False
        elif channel == config['irc']['np']:
            self.factory.handle.inIrcNp = False

    def kickedFrom(self, channel, kicker, message):
        clog.info('kickedFrom %s by %s: %s' % (channel, kicker, message), sys)
        self.join(self.channelName)

    def privmsg(self, user, channel, msg):
        clog.warning('(privmsg) message from %s in %s' % (user, channel), sys)
        if channel != self.channelName:
            return
        self.factory.handle.recIrcMsg(user, channel, msg)
        flag = 0
        self.logProcess(user, msg, flag)

    def action(self, user, channel, data):
        clog.debug('action %s by %s' % (data, user) , sys)
        self.factory.handle.recIrcMsg(user, channel, data, modifier='action')
        flag = 2 #action
        self.logProcess(user, data, flag)

    def sendChat(self, msg, action=False):
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        self._addQueue(msg, action)

    def partLeave(self, reason='Goodbye!'):
        self.leave(self.channelName, reason)
        self.quit(message='Shutting down...!')
        self.factory.handle.ircRestart = False

    def logProcess(self, user, msg, flag):
        timeNow = getTime()
        nickname = user.split('!')[0]
        i = user.find('~')
        j = user.find('@')
        username = user[i+1:j]
        host = user[j+1:]
        if nickname in self.nickdict:
            keyId = self.nickdict[nickname]['keyId']
            if keyId is None:
                # a callback for the keyId must already be registered
                clog.error('(logProcess) key None for user %s' % nickname, sys)
                dd = self.nickdict[nickname]['deferred']
                dd.addCallback(self.logChat, 3, timeNow, msg, flag)
            if keyId:
                d = self.logChat(keyId, 3, timeNow, msg, flag)
                
        else:
            self.nickdict[nickname] = {'keyId': None, 'deferred': None}
            clog.debug('(logProcess) added %s to nickdict' % nickname, sys)
            dd = self.queryOrAddUser(nickname, username, host)
            dd.addCallback(self.logChat, 3, timeNow, msg, flag)
            self.nickdict[nickname]['deferred'] = dd

    def queryOrAddUser(self, nickname, username, host):
        clog.debug('(queryOrAddUser) Quering %s:%s:%s' % (nickname, username, host), sys)
        d = database.dbQuery(('userId', 'flag'), 'ircUser',
               nickLower=nickname.lower(), username=username, host=host)
        d.addCallback(database.queryResult)
        values = (None, nickname.lower(), username, host, nickname, 0)
        d.addErrback(database.dbInsertReturnLastRow, 'ircUser', *values)
        clog.debug('(queryOrAddUser) Adding %s' % username, sys)
        d.addErrback(self.dbErr)
        d.addCallback(self.cacheKey, nickname)
        d.addErrback(self.dbErr)
        return d
        
    def dbErr(self, err):
        clog.error('(dbErr): %s' % err.value, sys)
        clog.error('(dbErr): %s' % dir(err), sys)
        clog.error('(dbErr): %s' % err.printTraceback(), sys)

    def returnKey(self, key):
        return defer.succeed(key)

    def cacheKey(self, res, nickname):
        clog.error('the key is %s:' % res[0], sys)
        assert res, 'no res at cacheKey'
        if res:
            clog.info("(cacheKey) cached %s's key %s" % (nickname, res[0]))
            self.nickdict[nickname]['keyId'] = res[0]
            return defer.succeed(res[0])

    def logIrcUser(self, nickname, username, host):
        """ logs IRC chat to IrcChat table """
        sql = 'INSERT OR IGNORE INTO IrcUser VALUES(?, ?, ?, ?, ?, ?)'
        binds = (None, nickname.lower(), username, host, nickname, 0)
        return database.operate(sql, binds)

    def queryUser(self, response, nickname, username, host):
        if nickname in self.nickdict:
            pass
        sql = 'SELECT userId FROM IrcUser WHERE nickLower=? AND username=? AND host=?'
        binds = (nickname.lower(), username, host)
        return database.query(sql, binds)

    def checkStatus(self, response, nickname):
        msg = 'STATUS %s' % nickname
        self.msg('NickServ', msg)
        
    def logChat(self, result, status, timeNow, msg, flag):
        status = 0 # we don't really need this
        msg = msg.decode('utf-8')
        sql = 'INSERT INTO IrcChat VALUES(?, ?, ?, ?, ?, ?)'
        binds = (None, result, status, timeNow, msg, flag)
        return database.operate(sql, binds)
    
class IrcFactory(ClientFactory):
    protocol = IrcProtocol

    def __init__(self, channel):
        self.channel = channel
        self.laters = []

    def clientConnectionLost(self, connector, reason):
        clog.warning('Connection Lost to IRC. Reason: %s' % reason, sys)
        self.reconnect()

    def clientConnectionFailed(self, connector, reason):
        clog.warning('Connection Failed to IRC. Reason: %s' % reason, sys)
        self.reconnect()

    def reconnect(self):
        # clean protocol loops/laters
        try:
            tools.cleanLoops(self.prot.loops)
            tools.cleanLaters(self.prot.laters)
        except(AttributeError):
            pass
        # clean factory (self) laters
        tools.cleanLaters(self.laters)
        if self.handle.ircRestart:
            self.laters.append(reactor.callLater(5, self.handle.ircConnect))
        else:
            self.handle.doneCleanup('irc')

