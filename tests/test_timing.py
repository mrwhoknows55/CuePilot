import logging
import unittest
from unittest.mock import patch

from cuepilot.timing import log_latency


class LatencyTests(unittest.TestCase):
    def test_logs_elapsed_milliseconds(self):
        logger = logging.getLogger("cuepilot.timing")
        with (
            patch("cuepilot.timing.perf_counter", side_effect=[10, 10.125]),
            self.assertLogs(logger, level="INFO") as logs,
        ):
            with log_latency(logger, "inference"):
                pass
        self.assertEqual(
            logs.records[0].getMessage(),
            "Latency: operation=inference duration_ms=125.00 status=ok",
        )

    def test_failure_is_timed_and_original_exception_survives(self):
        logger = logging.getLogger("cuepilot.timing")
        failure = RuntimeError("inference failed")
        with (
            self.assertLogs(logger, level="INFO") as logs,
            self.assertRaises(RuntimeError) as raised,
        ):
            with log_latency(logger, "inference"):
                raise failure
        self.assertIs(raised.exception, failure)
        self.assertIn("status=error", logs.records[0].getMessage())

    def test_frequent_operations_use_debug_level(self):
        logger = logging.getLogger("cuepilot.timing")
        with self.assertLogs(logger, level="DEBUG") as logs:
            with log_latency(logger, "vad", level=logging.DEBUG):
                pass
        self.assertEqual(logs.records[0].levelno, logging.DEBUG)
