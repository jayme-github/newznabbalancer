NewznabBalancer
===============

Do you use different Newznab sites indexing same or similar content and only giving a hand full of API hits/grabs a day? This little balacer allows you to auto-change to the next indexer if your grabs or hits exeed on the first one.

Should work with all Newznab sites and all Newznab clients (like Sickbeard and Couchpotato).


Usage
=====
```
Usage: newznabbalancer.py [options]
Simple webserver to balance Newznab API requests over several indexers.
Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -p PORT, --port=PORT  TCP port to bind to [default: 8000]
  -l, --list-accounts   List accounts in database
  -f, --list-fallbacks  List fallbacks of the last 24 hours
  -a, --add-account     Add a new account [-a <APIKEY> <URL> <3rd paramater if
                        fallback>]
  -d, --debug           debugging output
  --data-dir=DATADIR    Data directory where newznabbalancer.sqlite3 and logs
                        are stored
  --fake-key=FAKEKEY    The fake API key you use within your Newznab clients
                        [default: THISISAFAKEAPIKEYUSEDTOIDENTIFYMEATMYPROXY]
```
