from twisted.enterprise import adbapi
from yukari.customlogger import clog

syst = 'DATABASE'

def checkFileExistence():
    try:
        with open('data.db') as file:
            clog.info('Found data.db.', syst)
    except(IOError):
        clog.error('data.db not found! Initializing new database...', syst)
        from connections.database import createdb

def turnOnForeignKey(txn):
    txn.execute('PRAGMA FOREIGN_KEYS=ON')

def connect():
    dbp = adbapi.ConnectionPool('sqlite3', 'data.db', check_same_thread=False,
                                cp_max=1)
    clog.info('Opened data.db', syst)
    dbp.runInteraction(turnOnForeignKey)
    clog.info('Turned on foreign key constraint.', syst)
    return dbp

checkFileExistence()
connect()
