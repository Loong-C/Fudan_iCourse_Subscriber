import unittest
from unittest.mock import MagicMock, patch

from scripts.verify_login import verify_login


class LoginVerificationTests(unittest.TestCase):
    @patch('scripts.verify_login.time.sleep')
    @patch('scripts.verify_login.WebVPNSession')
    def test_cold_session_retries_with_fresh_session(self, factory, sleep):
        cold, ready = MagicMock(), MagicMock()
        cold.authenticate_icourse.side_effect = RuntimeError('WebVPN session cold — re-login needed')
        factory.side_effect = [cold, ready]
        verify_login()
        self.assertEqual(factory.call_count, 2)
        ready.login.assert_called_once()
        ready.authenticate_icourse.assert_called_once()
        sleep.assert_called_once_with(5)

    @patch('scripts.verify_login.time.sleep')
    @patch('scripts.verify_login.WebVPNSession')
    def test_credential_rejection_never_retries(self, factory, sleep):
        factory.return_value.login.side_effect = RuntimeError('Authentication failed (code=4020)')
        with self.assertRaisesRegex(RuntimeError, '4020'):
            verify_login()
        factory.assert_called_once()
        sleep.assert_not_called()

    @patch('scripts.verify_login.time.sleep')
    @patch('scripts.verify_login.WebVPNSession')
    def test_transient_retries_are_bounded(self, factory, sleep):
        factory.return_value.authenticate_icourse.side_effect = RuntimeError('WebVPN session cold')
        with self.assertRaisesRegex(RuntimeError, 'session cold'):
            verify_login(max_attempts=3)
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
