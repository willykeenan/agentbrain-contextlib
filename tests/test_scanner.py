"""Scanner: secrets and absolute home paths, values never returned."""
from __future__ import annotations

import json
import sys
import unittest


def _unload():
    for key in list(sys.modules):
        if key == 'agentbrain_contextlib' or key.startswith('agentbrain_contextlib.'):
            del sys.modules[key]


def _bind():
    global scan_text
    from agentbrain_contextlib.scanner import scan_text


def _token():
    return 'sk' + '-' + ('Abcd1234')


def _pem():
    return '-----BEGIN ' + 'PRIVATE KEY' + '-----'


def _api():
    return 'api' + '_key = ' + 'supersecretvalue'


def _home():
    return '/' + 'Users/' + 'ada/notes.txt'


def _linux():
    return '/' + 'home/' + 'ada/notes.txt'


def _win():
    return 'C:' + '\\' + 'Users' + '\\' + 'ada\\notes.txt'


class TestScanner(unittest.TestCase):
    def setUp(self):
        self.addCleanup(_unload)
        _bind()

    def test_clean_text_is_empty(self):
        text = 'Lamp character is Fl W 15s.\nSee project:BRIEF.md and url:https://www.iala.int/\n'
        self.assertEqual(scan_text(text), [])

    def test_secret_line_and_hint_hide_the_value(self):
        token = _token()
        text = 'ok\n' + token + '\nplain\n'
        hits = scan_text(text)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['kind'], 'secret')
        self.assertEqual(hits[0]['line'], 2)
        blob = json.dumps(hits)
        self.assertNotIn(token, blob)
        self.assertNotIn(token, hits[0]['hint'])

    def test_private_key_and_api_assignment(self):
        pem = _pem()
        api = _api()
        hits = scan_text(pem + '\n' + api + '\n')
        kinds = {hit['hint'] for hit in hits}
        self.assertIn('private-key block', kinds)
        self.assertIn('api-key assignment', kinds)
        blob = json.dumps(hits)
        self.assertNotIn(pem, blob)
        self.assertNotIn('supersecretvalue', blob)

    def test_absolute_home_paths(self):
        for builder in (_home, _linux, _win):
            value = builder()
            hits = scan_text('see ' + value + '\n')
            self.assertTrue(hits, value.__class__)
            self.assertTrue(all(hit['kind'] == 'abs-path' for hit in hits))
            self.assertNotIn(value, json.dumps(hits))
            self.assertEqual(hits[0]['hint'], 'absolute home path')
            self.assertEqual(hits[0]['line'], 1)

    def test_tilde_home(self):
        value = '~' + '/ada/notes.txt'
        hits = scan_text(value)
        self.assertEqual(hits[0]['kind'], 'abs-path')
        self.assertNotIn(value, json.dumps(hits))


if __name__ == '__main__':
    unittest.main()
