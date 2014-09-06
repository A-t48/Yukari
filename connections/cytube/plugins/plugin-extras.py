import random
from twisted.internet import reactor
class ExtrasPlugin(object):

    def _com_greet(self, cy, username, args):
        reactor.callLater(0.2, cy.sendAll, 'Hi, %s!' % username)

    def _com_wave(self, cy, username, args):
        waves = u'\uff89\uff7c' * random.randint(1,6)
        msg = 'waves at %s! %s' % (username, waves)
        reactor.callLater(0.2, cy.sendCy, '/me %s' % msg)
        reactor.callLater(0.2, cy.sendIrc, msg, action=True)

    def _cM_nextSong(self, cy, fdict):
        cy.sendCy('Next song!')

def setup():
    return ExtrasPlugin()
