from twisted.web.client import Agent, readBody
from yukari.config import cfg

syst = 'CYSESSIONID'
def retreiveSid(callback):
    """ Retrieves Cytube socket.io session id and calls callback with it"""
    from twisted.internet import reactor
    agent = Agent(reactor)
    url = ('http://%s:%s/socket.io/1/' % 
          (cfg['Cytube']['domain'], cfg['Cytube']['port'])).encode('utf8')
    d = agent.request('GET', url)
    d.addCallback(readBody)
    d.addCallback(processBody)
    d.addCallback(callback)
    return d

def processBody(body):
    if body is None:
        clog.error('No session ID from Cytube Socket.IO server', syst)
        return
    session = body.split(',')
    sid = session[0][:session[0].find(':')]
    return sid
