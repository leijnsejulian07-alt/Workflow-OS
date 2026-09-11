from __future__ import annotations

import functools
import unittest


def raises(expected_exception, match=None):
    case = unittest.TestCase()
    if match is None:
        return case.assertRaises(expected_exception)
    return case.assertRaisesRegex(expected_exception, match)


class _Mark:
    @staticmethod
    def parametrize(argnames, cases):
        names = (argnames,) if isinstance(argnames, str) else tuple(argnames)
        def decorator(func):
            @functools.wraps(func)
            def wrapper():
                case = unittest.TestCase()
                for raw in cases:
                    if len(names) == 1:
                        args = (raw,)
                    else:
                        args = tuple(raw)
                    with case.subTest(**dict(zip(names, args))):
                        func(*args)
            return wrapper
        return decorator


mark = _Mark()


def make_load_tests(namespace):
    def load_tests(loader, standard_tests, pattern):
        suite = unittest.TestSuite()
        suite.addTests(standard_tests)
        for name, value in sorted(namespace.items()):
            if name.startswith("test_") and callable(value):
                suite.addTest(unittest.FunctionTestCase(value, description=name))
        return suite
    return load_tests
