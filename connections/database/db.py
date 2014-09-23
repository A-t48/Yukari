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

def query(sql, binds):
    return dbp.runQuery(sql, binds)

def operate(sql, binds):
    return dbp.runOperation(sql, binds)

def insertRetLastRow(table, *args):
    return dbp.runInteraction(_dbInsert, table, *args)

def _dbInsert(txn, table, *args):
    sql, args = _makeInsert(table, *args)
    txn.execute(sql, args)
    return txn.lastrowid

def _makeInsert(table, *args):
    sql = 'INSERT INTO %s VALUES (' + ('?,' * (len(args)-1)) + '?)'
    return sql % table, args

def bulkInsert(fn, *args):
    return dbp.runInteraction(fn, *args)

def flagMedia(flag, mType, mId):
    sql = 'UPDATE Media SET flag=(flag|?) WHERE type=? AND id=?'
    binds = (flag, mType, mId)
    return operate(sql, binds)

def unflagMedia(flag, mType, mId):
    sql = 'UPDATE Media SET flag=(flag&?) WHERE type=? AND id=?'
    binds = (~flag, mType, mId)
    return operate(sql, binds)


def connect():
    dbp = adbapi.ConnectionPool('sqlite3', 'data.db', check_same_thread=False,
                                cp_max=1)
    clog.info('Opened data.db', syst)
    dbp.runInteraction(turnOnForeignKey)
    clog.info('Turned on foreign key constraint.', syst)
    return dbp

checkFileExistence()
dbp = connect()
