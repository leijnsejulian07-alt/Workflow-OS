import unittest

from workflow_os.adapters.whop_bounty_submission import (
    WHOP_API_VERSION_DATE,
    WhopBountyDeliverable,
    WhopBountySubmissionEvidence,
    build_workforce_submission_request,
    parse_workforce_submission_response,
)


class WhopBountySubmissionTests(unittest.TestCase):
    def _evidence(self, **overrides):
        values = {
            "user_credential_verified": True,
            "worker_identity_verified": True,
            "rights_verified": True,
            "campaign_requirements_verified": True,
            "deliverable_verified": True,
        }
        values.update(overrides)
        return WhopBountySubmissionEvidence(**values)

    def _deliverable(self, **overrides):
        values = {
            "deliverable_type": "content_url",
            "urls": ("https://www.tiktok.com/@creator/video/123",),
            "caption": "Verified campaign deliverable",
        }
        values.update(overrides)
        return WhopBountyDeliverable(**values)

    def test_builds_documented_user_submission_request(self):
        request = build_workforce_submission_request(
            bounty_id="bnty_example123",
            deliverable=self._deliverable(),
            evidence=self._evidence(),
            user_token="user-token-secret",
            idempotency_key="job-12345678",
        )
        self.assertEqual(request.url, "https://api.whop.com/api/v1/bounty_submissions")
        self.assertEqual(request.headers["Api-Version-Date"], WHOP_API_VERSION_DATE)
        self.assertEqual(request.headers["Idempotency-Key"], "job-12345678")
        self.assertEqual(request.json_body["bounty_id"], "bnty_example123")
        self.assertEqual(
            request.json_body["deliverable"]["urls"],
            ["https://www.tiktok.com/@creator/video/123"],
        )

    def test_rejects_incomplete_execution_evidence(self):
        fields = (
            "user_credential_verified",
            "worker_identity_verified",
            "rights_verified",
            "campaign_requirements_verified",
            "deliverable_verified",
        )
        for field in fields:
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_workforce_submission_request(
                    bounty_id="bnty_example123",
                    deliverable=self._deliverable(),
                    evidence=self._evidence(**{field: False}),
                    user_token="user-token-secret",
                    idempotency_key="job-12345678",
                )

    def test_requires_at_least_one_link_or_file(self):
        with self.assertRaises(ValueError):
            build_workforce_submission_request(
                bounty_id="bnty_example123",
                deliverable=self._deliverable(urls=(), file_ids=()),
                evidence=self._evidence(),
                user_token="user-token-secret",
                idempotency_key="job-12345678",
            )

    def test_rejects_unsafe_deliverable_urls(self):
        for url in (
            "http://example.com/video",
            "https://user:pass@example.com/video",
            "https://example.com:8443/video",
            "https://example.com",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                build_workforce_submission_request(
                    bounty_id="bnty_example123",
                    deliverable=self._deliverable(urls=(url,)),
                    evidence=self._evidence(),
                    user_token="user-token-secret",
                    idempotency_key="job-12345678",
                )

    def test_rejects_malformed_token_and_idempotency_key(self):
        for token, key in (("bad\ntoken", "job-12345678"), ("token", "short")):
            with self.subTest(token=token, key=key), self.assertRaises(ValueError):
                build_workforce_submission_request(
                    bounty_id="bnty_example123",
                    deliverable=self._deliverable(),
                    evidence=self._evidence(),
                    user_token=token,
                    idempotency_key=key,
                )

    def test_parses_only_confirmed_matching_submitted_response(self):
        result = parse_workforce_submission_response(
            status_code=201,
            payload={
                "id": "btys_submission123",
                "bounty_id": "bnty_example123",
                "status": "submitted",
            },
            expected_bounty_id="bnty_example123",
        )
        self.assertEqual(result.submission_id, "btys_submission123")
        self.assertEqual(result.status, "submitted")

    def test_rejects_unconfirmed_or_identity_drift_response(self):
        cases = (
            (409, {"id": "btys_submission123", "bounty_id": "bnty_example123", "status": "submitted"}),
            (201, {"id": "btys_submission123", "bounty_id": "bnty_other123", "status": "submitted"}),
            (201, {"id": "btys_submission123", "bounty_id": "bnty_example123", "status": "claimed"}),
            (201, {"id": "wrong_123", "bounty_id": "bnty_example123", "status": "submitted"}),
        )
        for status_code, payload in cases:
            with self.subTest(status_code=status_code, payload=payload), self.assertRaises(ValueError):
                parse_workforce_submission_response(
                    status_code=status_code,
                    payload=payload,
                    expected_bounty_id="bnty_example123",
                )


if __name__ == "__main__":
    unittest.main()
