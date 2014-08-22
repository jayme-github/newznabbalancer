import os
import tempfile
import shutil

# Use unittest2 on Python < 2.7.
try:
    import unittest2 as unittest
except ImportError:
    import unittest

from newznabbalancer.database import AccountDB


class AccountDBTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dbpath = os.path.join('testdb.sqlite3')
        self.db = AccountDB(self.dbpath)

    def tearDown(self):
        if os.path.isdir(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_dbfile_exists(self):
        self.assertTrue(os.path.isfile(self.dbpath),
                        'database file does not exist: %s' % self.dbpath)



if __name__ == '__main__':
    unittest.main()
