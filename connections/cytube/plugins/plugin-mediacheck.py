import json
import re
from twisted.internet import reactor, defer
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from connections.database import db
from yukari.customlogger import clog

syst = 'MediaCheck(P)'
class MediaCheck(object):
    """ Checks Youtube videos to make sure they can be played back in a browser.
        Non-playable media (embedding disabled, private, deleted, etc) will be
        flagged (Media) and deleted from the Cytube playlist.
        Videos are checked on queue and on changeMedia."""

    def _q_checkMedia(self, cy, fdict):
        media = fdict['args'][0]['item']['media']
        uid = fdict['args'][0]['item']['uid']
        title = media['title']
        mType = media['type']
        mId = media['id']
        d = self.checkVideoStatus(mId)
        d.addCallback(self.flagOrDelete, cy, mType, mId, title, uid)

    def _cM_checkMedia(self, cy, fdict):
        media = fdict['args'][0]
        uid = cy.currentUid
        title = media['title']
        mType = media['type']
        mId = media['id']
        d = self.checkVideoStatus(mId)
        d.addCallback(self.flagOrDelete, cy, mType, mId, title, uid)

    def checkVideoStatus(self, ytId):
        ytId = str(ytId)
        agent = Agent(reactor)
        url = ('http://gdata.youtube.com/feeds/api/videos/%s?v=2&alt=json'
               '&fields=yt:accessControl' % ytId)
        d = agent.request('GET', url, 
                          Headers({'Content-type':['application/json']}))
        d.addCallbacks(self.checkStatus, self.networkError, (ytId,))
        return d

    def checkStatus(self, response, ytId):
        d = readBody(response)
        if response.code == 403:
            return defer.succeed('Status403')
        elif response.code == 404:
            return defer.succeed('Status404')
        elif response.code == 503:
            return defer.succeed('Status503')
        else:
            d.addCallback(self.processYtCheck, ytId)
            return d

    def processYtCheck(self, body, ytId):
        try:
            res = json.loads(body)
        except(ValueError):
            clog.error('(processYtCheck) Error decoding JSON: %s' % body, syst)
            return 'BadResponse'

        actions = res['entry']['yt$accessControl']
        for action in actions:
            if action['action'] == 'embed':
                if action['permission'] == 'allowed':
                    clog.info('(processYtCheck) embed allowed for %s' % ytId)
                    return defer.succeed('EmbedOk')
        return defer.succeed('NoEmbed')

    def networkError(self, err):
        clog.error('Network Error: %s' % err.value, syst)
        return 'NetworkError'

    def flagOrDelete(self, res, cy, mType, mId, title, uid):
        if res == 'EmbedOk':
            clog.info('%s EmbedOk' % title, syst)
            db.unflagMedia(0b1, mType, mId)
        elif res in ('Status503', 'Status403', 'Status404', 'NoEmbed'):
            clog.warning('%s: %s' % (title, res), syst)
            cy.deleteMedia(uid)
            msg = 'Removing non-playable media %s' % title
            db.flagMedia(0b1, mType, mId)
            cy.sendCyWhisper(msg)

def setup():
    return MediaCheck()
