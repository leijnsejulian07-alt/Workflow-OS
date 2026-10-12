import unittest

from workflow_os.project_scope import (
    ProjectScope,
    ScopedAccessContext,
    ScopedResourceRef,
    ScopeMismatchError,
)


class ProjectScopeTests(unittest.TestCase):
    def setUp(self):
        self.scope = ProjectScope(chat_id="chat-1", project_id="project-a", repo_scope="owner/repo")
        self.context = ScopedAccessContext(scope=self.scope, state_epoch=7)
        self.ref = ScopedResourceRef.bind(
            context=self.context,
            resource_kind="builder-session",
            resource_id="session-1",
        )

    def test_bound_resource_accepts_exact_context(self):
        self.ref.require_context(self.context)

    def test_cross_project_access_fails_closed(self):
        other = ScopedAccessContext(
            scope=ProjectScope(chat_id="chat-1", project_id="project-b", repo_scope="owner/repo"),
            state_epoch=7,
        )
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_context(other)

    def test_cross_chat_access_fails_closed(self):
        other = ScopedAccessContext(
            scope=ProjectScope(chat_id="chat-2", project_id="project-a", repo_scope="owner/repo"),
            state_epoch=7,
        )
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_context(other)

    def test_cross_repo_access_fails_closed(self):
        other = ScopedAccessContext(
            scope=ProjectScope(chat_id="chat-1", project_id="project-a", repo_scope="owner/other"),
            state_epoch=7,
        )
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_context(other)

    def test_epoch_change_revokes_old_resource(self):
        newer = ScopedAccessContext(scope=self.scope, state_epoch=8)
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_context(newer)

    def test_future_epoch_resource_is_rejected_by_old_context(self):
        future = ScopedResourceRef.bind(
            context=ScopedAccessContext(scope=self.scope, state_epoch=8),
            resource_kind="preview",
            resource_id="preview-1",
        )
        with self.assertRaises(ScopeMismatchError):
            future.require_context(self.context)

    def test_unscoped_access_is_rejected(self):
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_context(None)

    def test_invalid_epochs_are_rejected(self):
        for value in (-1, True, 1.5, "7"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ScopedAccessContext(scope=self.scope, state_epoch=value)

    def test_invalid_or_ambiguous_ids_are_rejected(self):
        for value in ("", " leading", "has space", "../repo", "x" * 129):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ProjectScope(chat_id=value, project_id="project-a", repo_scope="owner/repo")

    def test_scope_digest_does_not_expose_raw_identifiers(self):
        self.assertEqual(len(self.scope.digest), 64)
        self.assertNotIn("project-a", self.scope.digest)
        self.assertNotIn("owner/repo", self.scope.digest)


if __name__ == "__main__":
    unittest.main()
