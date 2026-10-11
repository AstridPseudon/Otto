"""A facade cannot inherit a closed facade's injected owner authority."""
import gc
import unittest
from unittest.mock import patch
from otto.portfolio import herzchen_binding as binding

class OwnerPortBindingLifetimeTests(unittest.TestCase):
    def test_identity_reuse_does_not_select_foreign_owner_port(self):
        config=binding.HerzchenBindingConfig('test-owner','credential')
        sentinel=object()
        # Simulate the integer-ID collision the former process-global map
        # allowed after a previous facade was released.
        with patch.object(binding,'id',return_value=7,create=True):
            bound=binding.FiniteWorkOperations(port=object(),reader=object(),binding=config,
                orchestration_port=sentinel,orchestration_portfolio='portfolio',lifecycle_port=sentinel)
            unbound=binding.FiniteWorkOperations(port=object(),reader=object(),binding=config)
            self.assertIs(binding._orchestration_for(bound),sentinel)
            self.assertIsNone(binding._orchestration_for(unbound))
            self.assertIsNone(binding._orchestration_portfolio_for(unbound))
            self.assertIsNone(binding._lifecycle_for(unbound))
        before=len(binding._ORCHESTRATION_PORTS)
        del bound
        gc.collect()
        self.assertLess(len(binding._ORCHESTRATION_PORTS),before)
