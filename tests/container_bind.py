#!/usr/bin/env python3
"""Exercise published host-loopback ports with receiver binding inside Docker."""

import unittest

import verify as contract


class BridgeReceivers(contract.ContractTests):
    def setUp(self):
        super().setUp()
        self.env['MDLOGIC_CONTAINER_NETWORK'] = 'bridge'


if __name__ == '__main__':
    suite = unittest.TestSuite([BridgeReceivers('test_webhook_receivers')])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
