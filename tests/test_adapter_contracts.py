import unittest

from workflow_os.adapters.contracts import AccessMode, SourcePolicy


class SourcePolicyTests(unittest.TestCase):
    def test_source_policy_accepts_only_exact_https_allowlisted_hosts(self):
        policy = SourcePolicy(
            source_platform="example",
            allowed_hosts=frozenset({"api.example.com"}),
            access_mode=AccessMode.OFFICIAL_API,
        )

        self.assertTrue(policy.allows_url("https://api.example.com/campaigns"))
        self.assertFalse(policy.allows_url("http://api.example.com/campaigns"))
        self.assertFalse(policy.allows_url("https://evil.example/api.example.com"))
        self.assertFalse(policy.allows_url("https://api.example.com.evil.test/campaigns"))
        self.assertFalse(policy.allows_url("https://example.com/campaigns"))

    def test_source_policy_bounds_remote_resource_cost(self):
        with self.assertRaises(ValueError):
            SourcePolicy(
                source_platform="example",
                allowed_hosts=frozenset({"example.com"}),
                access_mode=AccessMode.PUBLIC_HTTP,
                max_response_bytes=10_485_761,
            )

        with self.assertRaises(ValueError):
            SourcePolicy(
                source_platform="example",
                allowed_hosts=frozenset({"example.com"}),
                access_mode=AccessMode.PUBLIC_HTTP,
                max_redirects=6,
            )

    def test_source_policy_requires_named_source_and_host_boundary(self):
        with self.assertRaises(ValueError):
            SourcePolicy(
                source_platform=" ",
                allowed_hosts=frozenset({"example.com"}),
                access_mode=AccessMode.PUBLIC_HTTP,
            )

        with self.assertRaises(ValueError):
            SourcePolicy(
                source_platform="example",
                allowed_hosts=frozenset(),
                access_mode=AccessMode.PUBLIC_HTTP,
            )


if __name__ == "__main__":
    unittest.main()
