import os
import tempfile
import shutil
import datetime
import string
import random

# Use unittest2 on Python < 2.7.
try:
    import unittest2 as unittest
except ImportError:
    import unittest

from newznabbalancer.database import AccountDB, ActionTypeError, ACTION_TYPES

def get_random_ascii_string(lengh=16):
    '''Return a random string

    May contain ASCII upper and lowercase as well as digits
    '''
    return ''.join(random.choice(
        string.ascii_letters + string.digits
        ) for i in range(lengh))

def get_dummy_account():
    return (get_random_ascii_string(), 'http://www.example.com')

def get_future_dt():
    '''Datetime instance in the future'''
    return datetime.datetime.now() + datetime.timedelta(
            hours=random.choice(range(1,25)))


class AccountDBTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dbpath = os.path.join(self.temp_dir, 'testdb.sqlite3')
        self.db = AccountDB(self.dbpath)

    def tearDown(self):
        del(self.db)
        if os.path.isdir(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_dbfile_exists(self):
        self.assertTrue(os.path.isfile(self.dbpath),
                        'database file does not exist: %s' % self.dbpath)

    def test_db_create(self):
        self.db.cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
        tables = [n[0] for n in self.db.cur.fetchall()]
        for name in ('accounts', 'fallbacks'):
            self.assertTrue(name in tables, '%s not in %r' % (name, tables))

    def test_add_account(self):
        apikey, url = get_dummy_account()
        self.db.add_account(apikey, url + '/')
        for atype in ACTION_TYPES:
            # add_account should strip last / from url
            self.assertEqual(self.db.get_account(atype),
                    (apikey, url))

    def test_add_account_fallback(self):
        apikey, url = get_dummy_account()
        self.db.add_account(apikey, url + '/', isFallback=True)
        for atype in ACTION_TYPES:
            # add_account should strip last / from url
            self.assertEqual(self.db.get_account(atype),
                    (apikey, url),
                    'Failed for %s' % atype)

    def test_next(self):
        apikey, url = get_dummy_account()
        self.db.add_account(apikey, url)

        for atype in ACTION_TYPES:
            self.assertEqual(self.db.get_next(atype), 0)
            future = get_future_dt()
            self.db.set_next(atype, apikey, future)
            self.assertEqual(self.db.get_next(atype),
                future)

    def test_no_account_left(self):
        apikey, url = get_dummy_account()
        self.db.add_account(apikey, url)

        for atype in ACTION_TYPES:
            future = get_future_dt()
            self.db.set_next(atype, apikey, future)
            self.assertEqual(self.db.get_account(atype), None,
                    'Failed for %s' % atype)

    def test_get_all_accounts(self):
        for i in range(1,random.choice((3,12))):
            apikey, url = get_dummy_account()
            self.db.add_account(apikey, url, random.choice((0,1)))
        self.assertEqual(len(self.db.get_all_accounts()), i,
                'Account count not equal')


    def test_get_all_fallbacks(self):
        count = dict.fromkeys(ACTION_TYPES, 0)
        for i in range(1,random.choice((3,12))):
            atype = random.choice(ACTION_TYPES)
            count[atype] += 1
            self.db._fallback(atype)

        fallbacks = self.db.get_last_fallbacks()
        self.assertEqual(len(fallbacks), i,
                'Fallback count not correct')

        for atype in ACTION_TYPES:
            self.assertEqual(count[atype],
                    len(list(filter(lambda f: f[0] == atype, fallbacks))),
                    '%s fallback count not correct' % atype)


    def test_fallback_wrong_atype(self):
        self.failUnlessRaises(ActionTypeError,
                self.db._fallback,
                'foo')

    def test_set_next_wrong_atype(self):
        self.failUnlessRaises(ActionTypeError,
                self.db.set_next,
                'foo', get_random_ascii_string(), datetime.datetime.now())

    def test_get_next_wrong_atype(self):
        self.failUnlessRaises(ActionTypeError,
                self.db.get_next,
                'foo')

    def test_get_account_wrong_atype(self):
        self.failUnlessRaises(ActionTypeError,
                self.db.get_account,
                'foo')
