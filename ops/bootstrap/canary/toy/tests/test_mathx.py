import unittest

from toy import mathx


class AddTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(mathx.add(2, 3), 5)
