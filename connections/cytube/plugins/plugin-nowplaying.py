class NowPlaying(object):

    def _cM_nowPlaying(self, cy, fdict):
        title = fdict['args'][0]['title']
        cy.sendCyWhisper('Now playing: %s' % title)

def setup():
    return NowPlaying()
