#!/usr/bin/env python3
"""Kill check: run the named test modules; print CHECK_PASS:<names> only if all pass.

Usage: python3 tools/check.py engine store web ...   (maps to tests/test_<name>.py)
       python3 tools/check.py package                (fresh venv install + CLI smoke)
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package_ok():
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / 'v'
        subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
        pip = venv / 'bin' / 'pip'
        subprocess.run([str(pip), 'install', '-q', str(ROOT)], check=True)
        exe = venv / 'bin' / 'ctxlib'
        for args in (['--help'], ['init', '--help'], ['brief', '--help'], ['search', '--help'], ['mcp', '--help'], ['doctor', '--help']):
            subprocess.run([str(exe), *args], check=True, stdout=subprocess.DEVNULL)
        lib = Path(tmp) / 'lib'
        subprocess.run([str(exe), 'init', str(lib), '--project', 'demo', '--name', 'Demo'], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(exe), '--library', str(lib), 'add', 'demo', 'decision', 'Use plain files', '--body', 'Decision: files first.', '--author', 'mara'], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(exe), '--library', str(lib), 'brief', 'demo'], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(exe), '--library', str(lib), 'doctor', 'demo'], check=True, stdout=subprocess.DEVNULL)
    return True


def main(names):
    ok = True
    modules = [n for n in names if n != 'package']
    if modules:
        sys.path.insert(0, str(ROOT / 'src'))
        sys.path.insert(0, str(ROOT / 'tests'))
        suite = unittest.defaultTestLoader.loadTestsFromNames(['test_' + n for n in modules])
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        ok = result.wasSuccessful() and result.testsRun > 0
    if ok and 'package' in names:
        try:
            ok = package_ok()
        except subprocess.CalledProcessError as e:
            print('package check failed:', e, file=sys.stderr)
            ok = False
    print(('CHECK_PASS:' if ok else 'CHECK_FAIL:') + ','.join(names))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
