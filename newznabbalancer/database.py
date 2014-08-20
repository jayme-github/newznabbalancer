import sqlite3
import os
import datetime

import logging


ACTION_TYPES = ('grab', 'hit') # possible API actions

class ActionTypeError(ValueError):
    message = 'atype must be one of %s' % ', '.join(
            '"%s"' % at for at in ACTION_TYPES)

class AccountDB(object):

    '''Handle account data. '''

    logger = logging.getLogger(__name__ + '.AccountDB')

    def __init__(self, dbpath):
        self.db = sqlite3.connect(dbpath, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
        self.cur = self.db.cursor()
        self.logger.debug('Connected to SQLite database at: %s', dbpath)
        if os.path.getsize(dbpath) == 0:
            self.create_database()

    def _fallback(self, atype):
        if not atype in ('grab', 'hit'):
            raise ActionTypeError
        self.logger.warning('No accounts with open %s left!' % atype)
        self.cur.execute('INSERT INTO fallbacks(atype, datetime) VALUES (?,?)',
                        (atype, datetime.datetime.now()))
        self.db.commit()
        
        self.cur.execute('SELECT apikey, url FROM accounts WHERE isfallback = 1')
        account = self.cur.fetchone()
        if not account:
            self.logger.warning('No fallback account defined, request will fail.')
            return None
        return account

    def create_database(self):
        self.logger.info('Database is empty, creating initial tables.')
        self.cur.execute('CREATE TABLE IF NOT EXISTS accounts (apikey TEXT PRIMARY KEY, url TEXT, isfallback INTEGER DEFAULT 0, nexthit TIMESTAMP, nextgrab TIMESTAMP)')
        self.cur.execute('CREATE TABLE IF NOT EXISTS fallbacks (atype TEXT, datetime TIMESTAMP)')
        self.db.commit()

    def add_account(self, apikey, url, isFallback=False):
        url = url.strip().rstrip('/')
        apikey = apikey.strip()
        if isFallback:
            self.cur.execute('INSERT INTO accounts(apikey, url, isfallback) VALUES (?, ?, 1)', (apikey, url))
        else:
            self.cur.execute('INSERT INTO accounts(apikey, url) VALUES (?, ?)', (apikey, url))
        self.db.commit()

    def set_next(self, atype, apikey, expiary):
        if not atype in ('grab', 'hit'):
            raise ActionTypeError
        field = 'next'+atype
        self.cur.execute('UPDATE accounts SET %s = ? WHERE apikey = ?' % field,
                        (expiary, apikey))
        self.db.commit()

    def get_account(self, atype):
        if not atype in ('grab', 'hit'):
            raise ActionTypeError
        field = 'next'+atype
        now = datetime.datetime.now()
        baseSQL = 'SELECT apikey, url FROM accounts WHERE isfallback = 0 AND '
        if atype == 'grab':
            # A grab consumes a hit and a grab...
            self.cur.execute(baseSQL + '(nextgrab IS NULL OR nextgrab < ?) AND (nexthit IS NULL OR nexthit < ?)', (now, now))
        else:
            self.cur.execute(baseSQL + '%s IS NULL OR %s < ? LIMIT 1' % (field, field), (now, ))
        account = self.cur.fetchone()
        if not account:
            return self._fallback(atype)
        return account
    
    def get_next(self, atype):
        if not atype in ('grab', 'hit'):
            raise ActionTypeError
        field = 'next'+atype
        self.cur.execute('SELECT %s FROM accounts ORDER BY %s LIMIT 1' % (field, field))
        nexta = self.cur.fetchone()
        if not nexta:
            return 0
        return nexta[0]

    def list_accounts(self):
        self.cur.execute('SELECT * FROM accounts')
        accounts = self.cur.fetchall()
        print '%d accounts:' % len(accounts)
        for r in accounts:
            print r

    def list_fallbacks(self):
        self.cur.execute('SELECT * FROM fallbacks WHERE datetime >= ? ORDER BY datetime',
                (datetime.datetime.now() - datetime.timedelta(hours=24), ))
        fallbacks = self.cur.fetchall()
        print '%d fallbacks:' % len(fallbacks)
        for r in fallbacks:
            print r

    def __del__(self):
        if self.db:
            self.db.commit()
            self.db.close()


