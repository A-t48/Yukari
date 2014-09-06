""" Creates the initial tables required for operation."""
import sqlite3, time
from yukari.config import cfg
from yukari.customlogger import clog

syst = 'CREATEDB'
con = sqlite3.connect('data.db')
con.execute('pragma foreign_keys=ON')

ircNick = cfg['irc']['nick']
cyName = cfg['Cytube']['username']

# CyUser table
clog.info('Creating CyUser table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS CyUser(
        userId INTEGER PRIMARY KEY,
        nameLower TEXT NOT NULL,
        registered INTEGER TEXT NOT NULL,
        nameOriginal TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 0,
        flag INTEGER NOT NULL DEFAULT 0,
        profileText TEXT,
        profileImgUrl TEXT,
        UNIQUE (nameLower, registered));""")

# insert Yukari,  server, and anonymous
clog.info('Inserting default values into CyUser table...', syst)
try:
    con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, cyName.lower(), 1, cyName, 3, 1, None, None))
    con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (2, '[server]', 1, '[server]', 0, 2, None, None))
    con.execute("INSERT INTO CyUser VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (3, '[anonymous]', 0, '[anonymous]', 0, 4, None, None))

except(sqlite3.IntegrityError):
    clog.error('Error inserting default values into CyUser table!', syst)

# User in/out
clog.info('Creating UserInOut table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS UserInOut(
        userId INTEGER NOT NULL,
        enter INTEGER NOT NULL,
        leave INTEGER NOT NULL,
        flag DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")

# IRC User table
clog.info('Creating IrcUser table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS IrcUser(
        userId INTEGER PRIMARY KEY,
        nickLower TEXT NOT NULL,
        username TEXT NOT NULL,
        host TEXT NOT NULL,
        nickOriginal TEXT NOT NULL,
        flag INTEGER NOT NULL DEFAULT 0,
        UNIQUE (nickLower, username, host));""")
try:
    clog.info('Inserting default values into IrcUser table...', syst)
    con.execute("INSERT INTO IrcUser VALUES (?, ?, ?, ?, ?, ?)",
                (1, ircNick.lower(), 'cybot', 'Yuka.rin.rin', ircNick, 1))

except(sqlite3.IntegrityError):
    clog.error('Error inserting default values into IrcUser table...', syst)
# Cy Chat table
clog.info('Creating CyChat table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS CyChat(
        chatId INTEGER PRIMARY KEY,
        userId INTEGER NOT NULL,
        chatTime INTEGER NOT NULL,
        chatCyTime INTEGER NOT NULL,
        chatMsg TEXT NOT NULL,
        modflair INTEGER,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")

# Cy PM table
clog.info('Creating CyPm table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS CyPm(
        chatId INTEGER PRIMARY KEY,
        userId INTEGER NOT NULL,
        pmTime INTEGER NOT NULL,
        pmCyTime INTEGER NOT NULL,
        pmMsg TEXT NOT NULL,
        flag INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(userId) REFERENCES CyUser(userId));""")
        
# IRC Chat table
clog.info('Creating IrcChat table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS IrcChat(
        chatId INTEGER PRIMARY KEY,
        userId INTEGER NOT NULL,
        status INTEGER,
        chatTime INTEGER NOT NULL,
        chatMsg TEXT,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY(userId) REFERENCES IrcUser(userId));""")

# media table
clog.info('Creating Media table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS Media(
        mediaId INTEGER PRIMARY KEY,
        type TEXT NOT NULL,
        id TEXT NOT NULL,
        dur INTEGER NOT NULL,
        title TEXT NOT NULL,
        by TEXT NOT NULL,
        flag INTEGER DEFAULT 0 NOT NULL,
        UNIQUE (type, id),
        FOREIGN KEY (by) REFERENCES CyUser(userId));""")

title = ('\xe3\x80\x90\xe7\xb5\x90\xe6\x9c\x88\xe3\x82\x86\xe3\x81\x8b\xe3'
         '\x82\x8a\xe3\x80\x91Mahou \xe9\xad\x94\xe6\xb3\x95\xe3\x80\x90\xe3'
         '\x82\xab\xe3\x83\x90\xe3\x83\xbc\xe3\x80\x91')
title = title.decode('utf-8')
try:
    clog.info('Inserting default values into Media table...', syst)
    con.execute("INSERT INTO Media VALUES (?, ?, ?, ?, ?, ?, ?)",
           (None, 'yt', '01uN4MCsrCE', 248, title, 1, 0))
except(sqlite3.IntegrityError):
    clog.error('Error inserting default values into Media table...', syst)

# queue table
clog.info('Creating Queue table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS Queue(
        queueId INTEGER PRIMARY KEY,
        mediaId INTEGER NOT NULL,
        userId INTEGER NOT NULL,
        time INTEGER NOT NULL,
        flag INTEGER DEFAULT 0 NOT NULL,
        FOREIGN KEY (userId) REFERENCES CyUser(userId),
        FOREIGN KEY (mediaId) REFERENCES media(mediaId));""")

# Usercount
clog.info('Creating Usercount table...', syst)
con.execute("""
        CREATE TABLE IF NOT EXISTS Usercount(
        time INTEGER NOT NULL,
        usercount INTEGER NOT NULL,
        anoncount INTEGER NOT NULL)
        """)

con.commit()
clog.info('Tables created.', syst)
con.close()
