try:
    import socketserver
except ImportError:
    import SocketServer as socketserver
try:
    from http.server import SimpleHTTPRequestHandler
except ImportError:
    from SimpleHTTPServer import SimpleHTTPRequestHandler
from threading import Thread
import signal
import re
import datetime
import requests
import logging
import newznabbalancer

# Global regexp definitions
re_WAIT = re.compile(r'.*(?:Wait|in) (?P<minutes>\d+) minutes.*')
re_GETNZB = re.compile(r'/getnzb/(?P<nzbId>\w+)\.nzb')
re_ERROR = re.compile(r'\<error code=\"(?P<code>\d+)\" description=\"(?P<description>.*)\"\/\>')


class NnbTCPServer(socketserver.ThreadingTCPServer):

    '''Inherit ThreadingTCPServer to allow additional parameters.'''

    def __init__(self, server_address, RequestHandlerClass, dbpath, fakekey, bind_and_activate=False):
        self.dbpath = dbpath
        self.fakekey = fakekey
        socketserver.ThreadingTCPServer.__init__(self, server_address, RequestHandlerClass, bind_and_activate)


class RequestHandler(SimpleHTTPRequestHandler):
    '''Handle GET requests and balance them over accounts in AccountDB '''

    server_version = "NewznabBalancer/" + newznabbalancer.__version__
    logger = logging.getLogger(__name__ + '.RequestHandler')

    def log_request(self, code='-', size='-'):
        '''Override BaseHTTPRequestHandler method

        We don't want httpd standard logging here...
        '''
        pass

    def log_message(self, format, *args):
        '''Log an arbitrary message.

        Use own logger instead of stderr
        '''
        from_string = self.address_string()
        if self.headers.get('User-Agent'):
            from_string = '%s@%s' % (self.headers.get('User-Agent'),
                                    self.address_string())
        self.logger.verbose('[%s] %s' % (from_string, format%args))

    def send_error(self, code, message=None, retryAfter=None):
        '''Send and log an error reply.

        Allow to set a Retry-After header.
        '''
        try:
            shortmsg, longmsg = self.responses[code]
        except KeyError:
            shortmsg, longmsg = '???', '???'
        if not message:
            message = shortmsg
        explain = longmsg
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
        '''Serve a GET request.'''
        if self.server.fakekey in self.path:
            # Init database
            self.adb = newznabbalancer.AccountDB(self.server.dbpath)

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
            if self.headers.get('User-Agent'):
                clientUserAgent['User-Agent'] = self.headers.get('User-Agent')
            
            # Replace fake API key
            url = baseUrl + self.path.replace(self.server.fakekey, apikey)
            self.log_message('GET %s', url)
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
            for header in filter(lambda h: h[0].lower().startswith('x-dnzb'), iter(r.headers.items())):
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


class NewznabBalancer(object):

    '''Simple controller for the NnbTCPServer instance'''

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
        
        print('Configure your clients with Newznab URL: "http://%s:%d"' % (self.address, self.port))
        print('And use the following API key: %s' % self.fakekey)
        self.httpd.serve_forever()

    def stop(self):
        print('Shutting down active request threads, preparing to exit')
        self.httpd.shutdown()
        self.httpd.server_close()

    def signal_handler(self, signal, frame):
        t = Thread(target=self.stop)
        t.start()
