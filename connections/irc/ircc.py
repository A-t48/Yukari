import importlib
import os
from twisted.internet import reactor
from twisted.internet.protocol import ClientFactory
from twisted.words.protocols import irc
from yukari.config import cfg
from yukari.customlogger import clog

cfg = cfg['irc']
syst = 'IRC'

class IrcProtocol(irc.IRCClient):
    lineRate = None

    def __init__(self):
        self.nickname = cfg['nick'].encode('utf8')
        self.channelName = cfg['channel'].encode('utf8')

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.factory.prot = self
        # tell Yukari irc is server connected
        self.factory.yuka.ircConnectionMade()

    def signedOn(self):
        self._identify()
        reactor.callLater(1, self.join, self.channelName)

    def joined(self, channel):
        self.factory.yuka.ircJoined(channel)

    def privmsg(self, user, channel, msg):
        msg = msg.decode('utf8')
        if channel != self.channelName:
            return
        nickname = user.split('!', 1)[0] # takes out name and host info
        clog.debug('message-%s:%s' % (user, msg), syst)
        self.factory.yuka.relayChat(nickname, msg, 'irc')

    def sendIrc(self, msg, action=False):
        msg = msg.encode('utf8')
        if action:
            self.describe(self.channelName, msg)
        else:
            self.msg(self.channelName, msg)

    def sendAll(self, msg):
        self.factory.yuka.sendAll(msg)

    def _identify(self):
        return

class IrcFactory(ClientFactory):
    protocol = IrcProtocol

    def __init__(self, channel):
        self.channel = channel

def startConnection():
    ircFactory = IrcFactory(cfg['channel'])
    return ircFactory
