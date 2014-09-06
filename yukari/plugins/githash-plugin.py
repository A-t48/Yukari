import subprocess
class GitHashPlugin(object):
    """naive git-hash version check"""
    # possible time of check to time of use error
    def __init__(self):
        input = ['git', 'rev-parse', '--short', 'HEAD']
        try:
            self.githash = subprocess.check_output(input).strip()
        except(subprocess.CalledProcessError):
            self.githash = 'Error'

    def _com_version(self, yuka, username, args):
        yuka.sendAll('Version: %s' % self.githash)

def setup():
    return GitHashPlugin()
