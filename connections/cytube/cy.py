import importlib
import json
import os
from twisted.internet import defer
from twisted.internet.defer import Deferred
from autobahn.twisted.websocket import WebSocketClientProtocol,\
                                       WebSocketClientFactory, \
                                       connectWS
from connections.database import db
from yukari.config import cfg
from yukari.customlogger import clog
from yukari.tools import getTime

cfg = cfg['Cytube']
syst = 'CYTUBE'


def importPlugins(paths):
    """ Imports any .py file in paths[0], and will also look through
    the first level directories for .py files to import """
    paths = ['connections/cytube/plugins/']
    try:
        files = os.listdir(paths[0])
        clog.info(str(files), 'files')
    except(OSError):
        clog.error('Plugin import error! Check that %s exists.' % paths[0],syst)
        return []
    # look for directories
    subdir = [paths[0]+i+'/' for i in files if os.path.isdir(paths[0]+i)]
    paths.extend(subdir)
    moduleNames = []
    for path in paths:
        moduleNames.extend([path + i[:-3] for i in os.listdir(path)
                        if not i.startswith('_') and i.endswith('.py')])
    moduleNames = [p.replace('/', '.') for p in moduleNames]
    modules = map(importlib.import_module, moduleNames)
    clog.warning(str(modules), 'modules')
    return modules

class CytubeProtocol(WebSocketClientProtocol):

    def __init__(self):
        modules = importPlugins('')
        self.triggers = {'commands':{},
                         'changeMedia': {},
                         'queue': {}}
        for module in modules:
            instance = module.setup()
            for method in dir(instance):
                # commands in cytube chat
                if method.startswith('_com_'):
                    trigger = '$%s' % method[5:]
                    self.triggers['commands'][trigger] = getattr(instance, method)
                elif method.startswith('_cM_'):
                    self.triggers['changeMedia'][method] = getattr(instance, method)
                elif method.startswith('_q_'):
                    self.triggers['queue'][method] = getattr(instance, method)

        self.userdict = {}
        self.username = cfg['username']
        self.receivedChatBuffer = False


    def onOpen(self):
        # give factory a reference of this protocol instance
        self.factory.prot = self
        # tell Yukari cytube is connected
        self.factory.yuka.cyOnConnect()
        self._initialize()

    def onClose(self, wasClean, code, reason):
        clog.warning('closed protocol connection', syst)

    def onMessage(self, msg, isBinary):
        if msg == '2::':
            self.sendMessage(msg) # return heartbeat

        elif msg.startswith('5:::{'):
            fstr = msg[4:]
            fdict = json.loads(fstr)
            clog.debug(('<--%s' % fdict).decode('unicode-escape'), syst)
            self._processFrame(fdict)

    def _processFrame(self, fdict):
        name = fdict['name']
        # send to the appropriate methods
        thunk = getattr(self, '_cy_%s' % (name,), None)
        if thunk is not None:
            thunk(fdict)

    def _sendf(self, dict): # 'sendFrame' is a WebSocket method name
        frame = json.dumps(dict)
        clog.info(('-->%s' % frame).decode('unicode-escape'), syst)
        frame = '5:::' + frame
        self.sendMessage(frame)
    
    def _cy_addUser(self, fdict):
        user = fdict['args'][0]
        timeNow = getTime()
        if user['name'] not in self.userdict:
            self._userJoin(user, timeNow)
            clog.info('Added %s to userdict' % user['name'], syst)
        else:
            clog.error('A user in userdict joined!' % user['name'], syst)

    def _cy_changeMedia(self, fdict):
        for key, method in self.triggers['changeMedia'].iteritems():
            method(self, fdict)

    def _cy_chatMsg(self, fdict):
        if not self.receivedChatBuffer:
            return
        processCommand = True
        args = fdict['args'][0]
        msg = args['msg']
        username = args['username']

        # check for commands
        # avoids interpreting a relayed chat message, and also for safety
        if username != self.username and msg.startswith('$'):
            command = msg.split()[0]
            index = msg.find(' ')
            if index != -1:
                commandArgs = msg[index+1:]
            else:
                commandArgs = ''
            if command in self.triggers['commands']:
                processCommand = False
                clog.info('Command triggered:%s:%s' % (command, commandArgs),
                           syst)
                self.triggers['commands'][command](self, username, commandArgs)

        # don't resend our own messages - Cytube server echos messages
        # (note: IRC does not)
        if username != self.username and username != '[server]':
            self.factory.yuka.relayChat(username, msg, 'cy', processCommand)

    def _cy_login(self, fdict):
        if fdict['args'][0]['success']:
            self._joinRoom()
        else:
            clog.error('Login error: Check credentials.', syst)

    def _cy_moveVideo(self, fdict):
        beforeUid = fdict['args'][0]['from']
        afterUid = fdict['args'][0]['after']
        self.movePlaylistItem(beforeUid, afterUid)

    def _cy_playlist(self, fdict):
        timeNow = getTime()
        self.playlist = fdict['args'][0]
        clog.info('playlist received!', syst)
        clog.info((str(fdict)).decode('unicode-escape'), syst)
        d = _dbSelectQueuerId(self, self.playlist)
        d.addCallback(bulkInsertMedia, _dbBulkInsertMediaTxn, self.playlist)
        d.addCallback(_dbLookupQueueId, self, self.playlist, timeNow)

    def _cy_queue(self, fdict):
        #for key, method in self.triggers['queue'].iteritems():
        #    method(self, fdict)
        timeNow = getTime()
        afterUid = fdict['args'][0]['after']
        mediad = fdict['args'][0]['item']
        isTemp = mediad['temp']
        media = mediad['media']
        queueby = mediad['queueby']
        title = media['title']
        dur = media['seconds']
        mType = media['type']
        mId = media['id']
        uid = mediad['uid']
        clog.info('%s queued %s' % (queueby, title), syst)
        
        # add to self.playlist
        self.addToPlaylist(mediad, afterUid)

        clog.info(str(media), syst)
        if queueby: # anonymous queue is empty string
            userId = self.userdict.get(queueby, {}).get('keyId', None)
        else:
            userId = 3 # Anonymous user
        if not userId:
            clog.error('%s queued media but is not in userdict' % queueby, syst)
            userId = 3 # give it to Anonymous user

        # insert or ignore into Media
        d = _dbInsertMedia(userId, mType, mId, dur, title)
        temp = 1 if isTemp else 0
        # insert into Queue
        d.addCallback(cbQueueId, self, uid, userId, mType, mId, timeNow, temp)
        d.addCallback(cy.setQueueId, mediad, playlist=False)

    def _cy_setCurrent(self, fdict):
        """ Saves the uid of the currently playing media """
        self.currentUid = fdict['args'][0]

    # timing could change in the future
    def _cy_setMotd(self, fdict):
        self.receivedChatBuffer = True
        self.factory.yuka.cyJoined()

    def _cy_userLeave(self, fdict):
        timeNow = getTime()
        username = fdict['args'][0]['name']
        if not username:
            return
        leftUser = self.userdict.pop(username, None)
        if leftUser:
            clog.info('%s has been removed from userdict.' % leftUser['name'],
                        syst)
            _dbLogoutUser(leftUser, timeNow)
        else:
            clog.error('A user not in userdict has left (%s) !' %
                        leftUser['name'], syst)

    def _cy_usercount(self, fdict):
        usercount = fdict['args'][0]
        self.usercount = usercount
        anoncount = usercount - len(self.userdict)
        _dbUsercount(usercount, anoncount, getTime())

    def _cy_userlist(self, fdict):
        self.userdict = {}
        userlist = fdict['args'][0]
        timeNow = getTime()
        for user in userlist:
           self._userJoin(user, timeNow)

    def _initialize(self):
        self._sendf({'name': 'login',
                    'args': {'name': cfg['username'],
                             'pw': cfg['password']}})

    def _joinRoom(self):
        self._sendf({'name': 'joinChannel',
                     'args': {'name': cfg['channel']}})

    def _userJoin(self, user, timeNow):
        self.userdict[user['name']] = user
        self.userdict[user['name']]['joined'] = timeNow
        self.userdict[user['name']]['keyId'] = None
        d = _returnKeyId(user, timeNow)
        d.addCallback(self._cbSetUserKeyId, user['name'])
        # keep a reference of deferred in each user value, so database
        # operations can be chained while the 'keyId' is being retrieved
        self.userdict[user['name']]['deferred'] = d

    def _cbSetUserKeyId(self, keyId, username):
        if not keyId:
            clog.error('Could not retrieve or add user %s for keyId!' %
                       username, syst)
            return
        keyId = str(keyId)
        clog.info('Obtained keyId for %s, KeyId: %s' % (username, keyId), syst)
        self.userdict[username]['keyId'] = keyId
        return keyId

    def setQueueId(self, queueId, mediad, playlist=False):
        """Set Queue Id to the media in self.playlist, and run the plug-in trigger
        for queue. If it's a playlist, we don't run the queue trigger"""
        uid = mediad['uid']
        i = self.getIndexFromUid(uid)
        self.playlist[i]['queueId'] = queueId
        clog.info('Set queueId of %s to uid %s' % (queueId, uid), syst)
        mType = self.playlist[i]['media']['type']
        mId = self.playlist[i]['media']['id']
        if not playlist:
            for key, method in self.triggers['queue'].iteritems():
                method(self, mediad)
    
    def getIndexFromUid(self, uid):
        """ Return media index of self.playlist given uid """
        try:
            media = (i for i in self.playlist if i['uid'] == uid).next()
            return self.playlist.index(media)
        except StopIteration as e:
            clog.error('(getIndexFromUid) Media uid %s not found' % uid, syst)

    def getUidFromTypeId(self, mType, mId):
        for media in self.playlist:
            if media['media']['id'] == mId:
                if media['media']['type'] == mType:
                    return media['uid']

    def addToPlaylist(self, mediad, afterUid):
        if afterUid == 'prepend':
            index = 0
        else:
            index = self.getIndexFromUid(afterUid)
        self.playlist.insert(index + 1, mediad)
        clog.debug('(addToPlaylist) Inserting uid %s %s after index %s' %
                   (mediad['uid'], mediad['media']['title'], index), syst)

    def movePlaylistItem(self, beforeUid, afterUid):
        # 'before' is the uid of the video that is going to move
        if afterUid == 'prepend':
            indexAfter = 0
        else:
            indexAfter = self.getIndexFromUid(afterUid)
        indexBefore = self.getIndexFromUid(beforeUid)
        if indexBefore > indexAfter and afterUid != 'prepend':
            indexAfter += 1
        self.playlist.insert(indexAfter, self.playlist.pop(indexBefore))

    def deleteMedia(self, uid):
        clog.info('Deleting media uid: %s' % uid, syst)
        self._sendf({'name': 'delete', 'args': uid})

    def sendCy(self, msg):
        self._sendf({'name': 'chatMsg', 'args': {'msg': msg}})

    def sendCyWhisper(self, msg):
        head = cfg['head']
        tail = cfg['tail']
        msg = '%s%s%s' % (head, msg, tail)
        self._sendf({'name': 'chatMsg', 'args': {'msg': msg}})


    def sendAll(self, msg):
        self.factory.yuka.sendAll(msg)

    def sendIrc(self, msg, action=False):
        self.factory.yuka.sendIrc(msg, action)

class CytubeFactory(WebSocketClientFactory):
    protocol = CytubeProtocol

    def clientConnectionLost(self, connector, reason):
        clog.warning('Client Connection Lost %s, %s' % (connector, reason),
                      syst)

    def clientConnectionFailed(self, connector, reason):
        clog.warning('Client Connection Failed %s, %s' % (connector, reason),
                     syst)

def startConnection(sid):
    domain = cfg['domain']
    port = cfg['port']
    wsurl = 'ws://%s:%s/socket.io/1/websocket/%s/' % (domain, port, sid)
    clog.info('WS url: %s' % wsurl, syst)
    cytubeFactory = CytubeFactory(wsurl)
    connectWS(cytubeFactory)
    return cytubeFactory

# databse CyUser
def _returnKeyId(user, timeNow):
    """ Retrieve user's keyId if exists, or
        enter a new row and return keyId """
    d = _lookupUserId(user)
    d.addCallback(_checkUserId, user, timeNow)
    return d

def _lookupUserId(user):
    sql = 'SELECT userId FROM CyUser WHERE nameLower=? AND registered=?'
    isRegistered = 1 if user['rank'] else 0
    binds = (user['name'].lower(), isRegistered)
    return db.query(sql, binds)

def _checkUserId(result, user, timeNow):
    if result:
        return result[0][0]
    # no row found. Need to add as new user
    else:
        return _dbAddNewCyUser(user, timeNow)

def _dbAddNewCyUser(user, timeNow):
    isRegistered = 1 if user['rank'] else 0
    values = (None, user['name'].lower(), isRegistered, user['name'], 0, 0,
             user['profile']['text'], user['profile']['image'])
    clog.info('Inserting new row for %s.' % user['name'], syst)
    return db.insertRetLastRow('CyUser', *values)

# database UserInOut
def _dbLogoutUser(user, timeNow):
    if user['keyId']:
        _dbLogUserTime(user['keyId'], user, timeNow)
    else:
        user['deferred'].addCallback(_dbLogUserTime, user, timeNow)

def _dbLogUserTime(keyId, user, timeNow):
    sql = 'INSERT INTO UserInOut VALUES (?, ?, ?, ?)'
    values = (keyId, user['joined'], timeNow, 0)
    db.operate(sql, values)
    return keyId

# database usercount
def _dbUsercount(usercount, anoncount, timeNow):
    sql = 'INSERT INTO Usercount VALUES (?, ?, ?)'
    values = (timeNow, usercount, anoncount)
    db.operate(sql, values)

def _dbInsertMedia(userId, mType, mId, dur, title):
    sql = 'INSERT OR IGNORE INTO Media VALUES (?, ?, ?, ?, ?, ?, ?)'
    binds = (None, mType, mId, dur, title, userId, 0)
    return db.operate(sql, binds)

def _dbInsertQueue(ignored, mType, mId, userId, timeNow, temp):
    sql = ('INSERT OR IGNORE INTO Queue VALUES (?, '
          '(SELECT mediaId FROM Media WHERE type=? AND id=?), ?, ?, ?)')
    binds = (None, mType, mId, userId, timeNow, temp)
    return db.operate(sql, binds)

def bulkInsertMedia(useridList, fn, playlist):
    d = _dbBulkInsertMedia(useridList, fn, playlist)
    d.addCallback(passthrough, useridList)
    return d

def passthrough(ignored, relay):
    return defer.succeed(relay)

def _dbBulkInsertMedia(useridList, fn, playlist):
    dbpl = []
    for userid, mediad in zip(useridList, playlist):
        media = mediad['media']
        dbpl.append((None, media['type'], media['id'], media['seconds'],
                     media['title'], userid, 0))
    return db.bulkInsert(fn, dbpl)

def _dbBulkInsertMediaTxn(txn, playlist):
    sql = 'INSERT OR IGNORE INTO Media VALUES (?, ?, ?, ?, ?, ?, ?)'
    txn.executemany(sql, playlist)

def _dbSelectQueuerId(cy, playlist):
    sql = 'SELECT UserId from CyUser WHERE nameLower=? AND registered=1'
    # Make a list of deferreds
    bindsList = [(mediad['queueby'],) for mediad in playlist]
    dblist = [db.query(sql, query) for query in bindsList]
    dl = defer.DeferredList(dblist, consumeErrors=False)
    dl.addCallback(cbSelectQueuerId)
    return dl

def cbSelectQueuerId(results):
    # results from a deferredList
    useridList = []
    for result in results:
        if result[0]:
           try:
               useridList.append(result[1][0][0])
           except(IndexError):
               # result[1] is [] because no queueId match
               # either guest or user not in CyUser
               useridList.append(1) # give to Yukari
    return defer.succeed(useridList)

def _dbLookupQueueId(useridList, cy, playlist, timeNow):
    #TODO deal with duplicate-allowed playlist
    sql = ('SELECT queueId FROM Queue WHERE mediaId = (SELECT mediaId FROM '
          'Media WHERE type=? AND id=?) ORDER BY queueId DESC LIMIT 1')
    for mediad, userId in zip(playlist, useridList):
        uid = mediad['uid']
        mType = mediad['media']['type']
        mId = mediad['media']['id']
        binds = (mType, mId)
        d = db.query(sql, binds)
        # flag = 2; added from this function, i.e. new queue from playlist
        d.addCallback(cbQueueId, cy, uid, userId, mType, mId, timeNow, 2)
        d.addCallback(cy.setQueueId, mediad, playlist=True)

def cbQueueId(queueId, cy, uid, userId, mType, mId, timeNow, flag):
    def _insertQueueLastRow(txn, sql, binds):
        txn.execute(sql, binds)
        return txn.lastrowid

    if queueId:
        return defer.succeed(queueId[0][0])
    else:
        sql = ('INSERT INTO Queue VALUES (?, (SELECT mediaId FROM Media WHERE '
               'type=? AND id=?), ?, ?, ?)')
        binds = (None, mType, mId, userId, timeNow, flag)
        return db.dbp.runInteraction(_insertQueueLastRow, sql, binds)
