import unittest
import os
import subprocess as sp


class TestBadTemplates(unittest.TestCase):

    def test_missing_base_template(self):
        os.chdir("missing-base-template")
        res = sp.run("ssg", stderr=sp.PIPE)
        self.assertNotEqual(
            res.stderr.decode().find("'nothing' not found in search path"),
            -1)
