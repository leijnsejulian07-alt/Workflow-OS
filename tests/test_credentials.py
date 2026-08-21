import unittest
from unittest.mock import patch

from workflow_os.adapters.tiktok_credentials import execute_tiktok_direct_post_with_credential
from workflow_os.credentials import CredentialLease, CredentialRef, lease_credential
from workflow_os.submission_execution import SubmissionAttemptResult


class Provider:
    def __init__(self, value):
        self.value = value
        self.refs = []

    def lease(self, ref):
        self.refs.append(ref)
        return CredentialLease(self.value)


class CredentialBoundaryTests(unittest.TestCase):
    def test_reference_contains_no_secret_value_and_is_normalized(self):
        ref = CredentialRef(" TikTok ", "creator-17", "access_token")
        self.assertEqual(ref.platform, "tiktok")
        self.assertEqual(ref.account_id, "creator-17")
        self.assertNotIn("tok_super_sensitive_123", repr(ref))

    def test_lease_redacts_string_and_repr(self):
        secret = "tok_super_sensitive_123"
        lease = CredentialLease(secret)
        self.assertEqual(lease.reveal(), secret)
        self.assertNotIn(secret, repr(lease))
        self.assertNotIn(secret, str(lease))
        self.assertEqual(str(lease), "<redacted>")

    def test_provider_must_return_a_lease(self):
        class BadProvider:
            def lease(self, ref):
                return "raw-secret"

        with self.assertRaises(TypeError):
            lease_credential(BadProvider(), CredentialRef("tiktok", "a1", "access_token"))

    def test_malformed_secret_is_rejected(self):
        for value in ("", "bad\nsecret", "bad\rsecret"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    CredentialLease(value)

    def test_tiktok_wrapper_resolves_just_in_time(self):
        ref = CredentialRef("tiktok", "creator-17", "access_token")
        provider = Provider("tok_abc123")
        sentinel = SubmissionAttemptResult(outcome="UNKNOWN")

        with patch(
            "workflow_os.adapters.tiktok_credentials.execute_tiktok_direct_post_attempt",
            return_value=sentinel,
        ) as execute:
            result = execute_tiktok_direct_post_with_credential(
                object(),
                options=object(),
                credential_ref=ref,
                credential_provider=provider,
                asset_root="assets",
                transport=object(),
                sleep=lambda _: None,
            )

        self.assertIs(result, sentinel)
        self.assertEqual(provider.refs, [ref])
        self.assertEqual(execute.call_args.kwargs["access_token"], "tok_abc123")
        self.assertNotIn("tok_abc123", repr(ref))

    def test_tiktok_wrapper_rejects_cross_platform_reference_before_resolution(self):
        provider = Provider("tok_abc123")
        with self.assertRaises(ValueError):
            execute_tiktok_direct_post_with_credential(
                object(),
                options=object(),
                credential_ref=CredentialRef("youtube", "creator-17", "access_token"),
                credential_provider=provider,
                asset_root="assets",
                transport=object(),
                sleep=lambda _: None,
            )
        self.assertEqual(provider.refs, [])

    def test_tiktok_wrapper_rejects_wrong_secret_type_before_resolution(self):
        provider = Provider("tok_abc123")
        with self.assertRaises(ValueError):
            execute_tiktok_direct_post_with_credential(
                object(),
                options=object(),
                credential_ref=CredentialRef("tiktok", "creator-17", "refresh_token"),
                credential_provider=provider,
                asset_root="assets",
                transport=object(),
                sleep=lambda _: None,
            )
        self.assertEqual(provider.refs, [])


if __name__ == "__main__":
    unittest.main()
