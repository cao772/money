import unittest

import ledger
import money


class LedgerTests(unittest.TestCase):
    def test_evidenced_totals_stay_separate_from_payouts_and_other_currencies(self):
        db = money.connect(":memory:")
        self.addCleanup(db.close)
        self.assertIsNone(money.report(db)["net_profit"])
        example = {"id":"synthetic-1", "account":"sample-store", "currency":"USD",
                   "starts":"2025-01-01", "ends":"2025-01-31", "sales":"10.00",
                   "refunds":"1", "fees":"0.80", "expenses":"2.00", "evidence":"synthetic fixture"}
        self.assertTrue(ledger.record(db, example))
        self.assertFalse(ledger.record(db, example))
        with self.assertRaises(ValueError):
            ledger.record(db, {**example, "id":"overlap"})
        with self.assertRaises(ValueError):
            ledger.record(db, {**example, "id":"incomplete", "currency":"CNY", "fees":None})
        with self.assertRaises(ValueError):
            ledger.record(db, {**example, "id":"unverified", "currency":"EUR", "payout":"5.00"})
        self.assertTrue(ledger.record(db, {**example,"id":"synthetic-2","currency":"CNY","sales":"0.50",
                                          "refunds":"0","fees":"0","payout":"0","payout_evidence":"synthetic bank report"}))
        report = money.report(db)
        self.assertEqual(report["net_profit"], {"CNY":"-1.50","USD":"6.20"})
        self.assertEqual(report["actual_revenue"]["USD"], "9.00")
        self.assertIsNone(report["by_currency"]["USD"]["settled"])
        self.assertEqual(report["by_currency"]["CNY"]["settled"], "0.00")
