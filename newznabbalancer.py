#!/usr/bin/env python

__version__ = '0.1'

import SimpleHTTPServer
import SocketServer
import requests
import sqlite3
import datetime
import re
from optparse import OptionParser
import os
from threading import Thread
import signal
import logging

# Defaults
PORT = 8000
FAKEKEY = 'THISISAFAKEAPIKEYUSEDTOIDENTIFYMEATMYPROXY'
DBNAME = 'newznabbalancer.sqlite3'
LOGNAME = 'newznabbalancer.log'

# Global regexp definitions
re_WAIT = re.compile(ur'.*(?:Wait|in) (?P<minutes>\d+) minutes.*')
re_GETNZB = re.compile(ur'/getnzb/(?P<nzbId>\w+)\.nzb')
re_ERROR = re.compile(ur'\<error code=\"(?P<code>\d+)\" description=\"(?P<description>.*)\"\/\>')

# Setup logging
# Create a new debug level that always passes filter
# to log status messages (loggin.Logger.status is taken)
# like httpd request lines etc.
VERBOSE_LEVEL_NUM = 51
logging.addLevelName(VERBOSE_LEVEL_NUM, "VERBOSE")
def verbose(self, message, *args, **kws):
    # Yes, logger takes its '*args' as 'args'.
    if self.isEnabledFor(VERBOSE_LEVEL_NUM):
        self._log(VERBOSE_LEVEL_NUM, message, args, **kws) 
logging.Logger.verbose = verbose
logger = logging.getLogger('NNB')

class AccountDB(object):
    logger = logging.getLogger(logger.name + '.AccountDB')

    def __init__(self, dbpath):
        self.db = sqlite3.connect(dbpath, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
        self.cur = self.db.cursor()
        if os.path.getsize(dbpath) == 0:
            self.create_database()

    def _fallback(self, atype):
        if not atype in ('grab', 'hit'):
            raise ValueError('atype must be "grab" or "hit"')
        self.logging.warning('No accounts with open %s left!!!' % atype)
        self.cur.execute('INSERT INTO fallbacks(atype, datetime) VALUES (?,?)',
                        (atype, datetime.datetime.now()))
        self.db.commit()
        
        self.cur.execute('SELECT apikey, url FROM accounts WHERE isfallback = 1')
        account = self.cur.fetchone()
        if not account:
            self.logging.warning('No fallback account defined, request will fail')
            return None
        return account

    def create_database(self):
        self.logger.info('Creating a fresh database')
        self.cur.execute('CREATE TABLE IF NOT EXISTS accounts (apikey TEXT PRIMARY KEY, url TEXT, isfallback INTEGER DEFAULT 0, nexthit TIMESTAMP, nextgrab TIMESTAMP)')
        self.cur.execute('CREATE TABLE IF NOT EXISTS fallbacks (atype TEXT, datetime TIMESTAMP)')
        self.db.commit()

    def add_account(self, apikey, url, isFallback=False):
        url = url.strip().rstrip('/')
        apikey = apikey.strip()
        if fallback:
            self.cur.execute('INSERT INTO accounts(apikey, url, isfallback) VALUES (?, ?, 1)', (apikey, url))
        else:
            self.cur.execute('INSERT INTO accounts(apikey, url) VALUES (?, ?)', (apikey, url))
        self.db.commit()

    def set_next(self, atype, apikey, expiary):
        if not atype in ('grab', 'hit'):
            raise ValueError('atype must be "grab" or "hit"')
        field = 'next'+atype
        self.cur.execute('UPDATE accounts SET %s = ? WHERE apikey = ?' % field,
                        (expiary, apikey))
        self.db.commit()

    def set_nexthit(self, apikey, expiary):
        return self.set_next('hit', apikey, expiary)
    
    def set_nextgrab(self, apikey, expiary):
        return self.set_next('grab', apikey, expiary)

    def get_account(self, atype):
        if not atype in ('grab', 'hit'):
            raise ValueError('atype must be "grab" or "hit"')
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
    
    def get_hit_account(self):
        return self.get_account('hit')
    
    def get_grab_account(self):
        return self.get_account('grab')

    def get_next(self, atype):
        if not atype in ('grab', 'hit'):
            raise ValueError('atype must be "grab" or "hit"')
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


class RequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
    logger = logging.getLogger(logger.name + '.RequestHandler')

    def log_message(self, format, *args):
        self.logger.verbose('[%s] %s' % (self.address_string(), format%args))

    def send_error(self, code, message=None, retryAfter=None):
        try:
            short, long = self.responses[code]
        except KeyError:
            short, long = '???', '???'
        if not message:
            message = short
        explain = long
        self.log_error("code %d, message %s", code, message)
        self.send_response(code, message)
        if retryAfter:
            self.send_header('Retry-After', retryAfter)
        self.end_headers()
        self.wfile.write(self.error_message_format %
                         {'code': code,
                          'message': message,
                          'explain': explain})

    def do_GET(self):
        if self.server.fakekey in self.path:
            # Init database
            self.adb = AccountDB(self.server.dbpath)

            # Determine action type
            if 't=get' in self.path:
                atype = 'grab'
            elif 'getnzb' in self.path:
                atype = 'grab'
                # rewrite getnzb call to t=get for better error handling
                m = re_GETNZB.match(self.path)
                if m:
                    nzbId = m.groupdict().get('nzbId')
                    if nzbId:
                        self.path = '/api?t=get&id=%s&apikey=%s' % (nzbId, self.server.fakekey)
                else:
                    self.logger.error('Failed to parse nzbId from "getnzb" URL, continuing without modification')
            else:
                atype = 'hit'
            
            # Get a API key
            apikey, baseUrl = self.adb.get_account(atype)
            if not apikey:
                self.send_error(503, 'No keys with active %s\'s left' % atype,  self.adb.get_next(atype))
                return

            # Reuse the clients user agent (sickbeard, couchpotato, ...)
            clientUserAgent = {}
            if 'user-agent' in self.headers.dict:
                clientUserAgent['User-Agent'] = self.headers.dict.get('user-agent')
            
            # Replace fake API key
            url = baseUrl + self.path.replace(self.server.fakekey, apikey)
            self.log_message('Fetching: "%s"', url)
            try:
                r = requests.get(url, headers=clientUserAgent)
            except requests.exceptions.RequestException as e:
                self.send_error(503, str(e), datetime.datetime.now() + datetime.timedelta(minutes=5))
                return

            # Handle "too many requests" errors (e.g. use different API key)
            if r.status_code == 429:
                match = re_WAIT.search(r.text)
                if match:
                    minutes = int(match.groupdict().get('minutes', 0))
                    expiary = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
                    self.adb.set_next(atype, apikey, expiary)
                return self.do_GET()
            
            self.send_response(r.status_code)
            self.send_header('Content-type', r.headers.get('content-type', 'text/html'))
            # Forward possible x-dnzb headers to client
            for header in filter(lambda h: h[0].lower().startswith('x-dnzb'), r.headers.iteritems()):
                 self.send_header(*header)
            self.end_headers()
            data = r.text.encode('utf-8')

            # Remote server returned an error, just pass the data
            if r.status_code != 200:
                self.wfile.write(data)
                return
            
            # Check for errors in response data
            m = re_ERROR.search(data)
            if m:
                self.log_error('Data contains an error, code: "%s", description: "%s"',
                                m.groupdict().get('code'),
                                m.groupdict().get('description'))
                # FIXME: Can we do anything about it?

            if atype == 'hit':
                # rewrite grab URLs to use the proxy...(am I smart :))
                # oh, and rewrite the API key too (even smarter)
                data = data.replace(baseUrl + '/getnzb',
                                        'http://%s:%d/getnzb' % self.server.server_address
                                        ).replace(apikey, self.server.fakekey)
            
            self.wfile.write(data)

        else:
            self.log_error('Unhandeled request: "%s"' % self.path)
            self.send_response(404)
            self.send_header('Content-type','text/html')
            self.end_headers()
            # TODO Write out some kind of help message...
            self.wfile.write('<p>Unhandeled request: "%s"</p>' % self.path)

class NnbTCPServer(SocketServer.ThreadingTCPServer):
    def __init__(self, server_address, RequestHandlerClass, dbpath, fakekey, bind_and_activate=False):
        self.dbpath = dbpath
        self.fakekey = fakekey
        SocketServer.ThreadingTCPServer.__init__(self, server_address, RequestHandlerClass, bind_and_activate)

class NewznabBalancer(object):
    def __init__(self, address, port, dbpath, fakekey):
        self.address = address
        self.port = port
        self.dbpath = dbpath
        self.fakekey = fakekey
        signal.signal(signal.SIGTERM, self.signal_handler)

    def start(self):
        self.httpd = NnbTCPServer((self.address, self.port), RequestHandler, dbpath=self.dbpath, fakekey=self.fakekey)
        self.httpd.allow_reuse_address = True
        self.httpd.daemon_threads = True
        self.httpd.server_bind()
        self.httpd.server_activate()
        
        print 'Configure your clients with Newznab URL: "http://%s:%d"' % (self.address, self.port)
        print 'And use the following API key: %s' % self.fakekey
        self.httpd.serve_forever()

    def stop(self):
        print 'Shutting down active request threads, preparing to exit'
        self.httpd.shutdown()
        self.httpd.server_close()

    def signal_handler(self, signal, frame):
        t = Thread(target=self.stop)
        t.start()

if __name__ == '__main__':
    description = 'Simple webserver to balance Newznab API requests over several indexers.'
    parser = OptionParser(version=0.1, description=description)
    parser.add_option('-p', '--port', action='store', dest='port',
            type='int', default=PORT, help='TCP port to bind to [default: %default]')
    parser.add_option('-l', '--list-accounts', action='store_true', dest='listaccounts',
            default=False, help='List accounts in database')
    parser.add_option('-f', '--list-fallbacks', action='store_true', dest='listfallbacks',
            default=False, help='List fallbacks of the last 24 hours')
    parser.add_option('-a', '--add-account', action='store_true', dest='addaccount',
            default=False, help='Add a new account [-a <APIKEY> <URL> <3rd paramater if fallback>]')
    parser.add_option('-d', '--debug', action='store_true', dest='_debug', help='debugging output')
    parser.add_option('--data-dir', action='store', dest='datadir', type='string',
            default='/var/newznabbalancer', help='Data directory where %s and logs are stored' %(DBNAME,))
    parser.add_option('--fake-key', action='store', dest='fakekey', type='string',
            default=FAKEKEY, help='The fake API key you use within your Newznab clients [default: %default]')
    (options, args) = parser.parse_args()

    if os.path.isdir(options.datadir):
        logpath = os.path.join(options.datadir, LOGNAME)
    else:
        logpath = LOGNAME
    logging.basicConfig(format='%(asctime)s - %(name)s.%(funcName)s - %(levelname)s - %(message)s',
                        filename=LOGNAME, level=logging.WARNING)
    if options._debug:
        logging.getLogger('NNB').setLevel(logging.DEBUG)
        logger.debug('Running in debug mode')

    dbpath = os.path.join(options.datadir, DBNAME)
    if not os.path.isfile(dbpath) and os.path.isfile(DBNAME):
        dbpath = DBNAME

    if options.listaccounts or options.listfallbacks or options.addaccount:
        # database stuff
        db = AccountDB(dbpath)
        if options.listaccounts:
            db.list_accounts()
        if options.listfallbacks:
            db.list_fallbacks()
        if options.addaccount:
            if len(args) == 3:
                db.add_account(args[0], args[1], True)
                print 'Added apikey "%s" with URL "%s" as fallback' % (args[0], args[1])
            elif len(args) == 2:
                db.add_account(args[0], args[1])
                print 'Added apikey "%s" with URL "%s"' % (args[0], args[1])
            else:
                parser.error('Need at least two arguments (API key and API URL!\nAdd a third parameter if you want to add the account as fallback.\n -a <apikey> <url> <shouldbefallbackyo>')
    else:
        nnb = NewznabBalancer('localhost', options.port, dbpath, options.fakekey)
        try:
            nnb.start()
        except KeyboardInterrupt:
            nnb.stop()
