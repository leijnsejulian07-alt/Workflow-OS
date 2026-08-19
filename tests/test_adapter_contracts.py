import pytest

from workflow_os.adapters.contracts import AccessMode, SourcePolicy


def test_source_policy_accepts_only_exact_https_allowlisted_hosts():
    policy = SourcePolicy(
        source_platform="example",
        allowed_hosts=frozenset({"api.example.com"}),
        access_mode=AccessMode.OFFICIAL_API,
    )

    assert policy.allows_url("https://api.example.com/campaigns") is True
    assert policy.allows_url("http://api.example.com/campaigns") is False
    assert policy.allows_url("https://evil.example/api.example.com") is False
    assert policy.allows_url("https://api.example.com.evil.test/campaigns") is False
    assert policy.allows_url("https://example.com/campaigns") is False


def test_source_policy_bounds_remote_resource_cost():
    with pytest.raises(ValueError):
        SourcePolicy(
            source_platform="example",
            allowed_hosts=frozenset({"example.com"}),
            access_mode=AccessMode.PUBLIC_HTTP,
            max_response_bytes=10_485_761,
        )

    with pytest.raises(ValueError):
        SourcePolicy(
            source_platform="example",
            allowed_hosts=frozenset({"example.com"}),
            access_mode=AccessMode.PUBLIC_HTTP,
            max_redirects=6,
        )


def test_source_policy_requires_named_source_and_host_boundary():
    with pytest.raises(ValueError):
        SourcePolicy(
            source_platform=" ",
            allowed_hosts=frozenset({"example.com"}),
            access_mode=AccessMode.PUBLIC_HTTP,
        )

    with pytest.raises(ValueError):
        SourcePolicy(
            source_platform="example",
            allowed_hosts=frozenset(),
            access_mode=AccessMode.PUBLIC_HTTP,
        )
