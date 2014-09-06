
class NowPlaying(object):

    def _cM_nowPlaying(self, cy, fdict):
        title = fdict['args'][0]['title']
        cy.sendCy('Now playing: %s' % title)

def setup():
    return NowPlaying()
