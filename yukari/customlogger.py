import logging
import sys
from twisted.python import log
from yukari.config import cfg

cfg = cfg['logger']

class LevelFileLogObserver(log.FileLogObserver):
    def __init__(self, f, level=logging.INFO):
        log.FileLogObserver.__init__(self, f)
        self.logLevel = level

    def emit(self, eventDict):
        if eventDict['isError']:
            level = logging.ERROR
            self.write('\033[91m')
            log.FileLogObserver.emit(self, eventDict)
            self.write('\033[0m')
            return
        elif 'level' in eventDict:
            level = eventDict['level']
        else:
            level = logging.INFO
        if level > self.logLevel and level == logging.ERROR:
            self.write('\033[91m')
        elif level == logging.WARNING:
            self.write('\033[33m')
        log.FileLogObserver.emit(self, eventDict)
        self.write('\033[0m') # reset any color

class CustomLog():
    """ logging shortcut """
    def debug(self, msg, syst=None):
        if syst:
            if not cfg.get(syst.lower(), None) == 'debug':
                return
        msg = msg.encode('utf8')
        log.msg(msg, level=logging.DEBUG, system=syst)
    def info(self, msg, syst=None):
        msg = msg.encode('utf8')
        log.msg(msg, level=logging.INFO, system=syst)
    def warning(self, msg, syst=None):
        msg = msg.encode('utf8')
        log.msg(msg, level=logging.WARNING, system=syst)
    def error(self, msg, syst=None):
        msg = msg.encode('utf8')
        log.msg(msg, level=logging.ERROR, system=syst)
    def critical(self, msg, syst=None):
        msg = msg.encode('utf8')
        log.msg(msg, level=logging.CRITICAL, system=syst)

clog = CustomLog()
logger = LevelFileLogObserver(sys.stdout, level=logging.DEBUG)
log.addObserver(logger.emit)
