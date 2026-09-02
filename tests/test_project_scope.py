import unittest

from workflow_os.project_scope import ProjectScope, ScopedResourceRef, ScopeMismatchError


class ProjectScopeTests(unittest.TestCase):
    def setUp(self):
        self.scope = ProjectScope(chat_id="chat-1", project_id="project-a", repo_scope="owner/repo")
        self.ref = ScopedResourceRef.bind(scope=self.scope, resource_kind="builder-session", resource_id="session-1")

    def test_bound_resource_accepts_exact_scope(self):
        self.ref.require_scope(self.scope)

    def test_cross_project_access_fails_closed(self):
        other = ProjectScope(chat_id="chat-1", project_id="project-b", repo_scope="owner/repo")
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_scope(other)

    def test_cross_chat_access_fails_closed(self):
        other = ProjectScope(chat_id="chat-2", project_id="project-a", repo_scope="owner/repo")
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_scope(other)

    def test_cross_repo_access_fails_closed(self):
        other = ProjectScope(chat_id="chat-1", project_id="project-a", repo_scope="owner/other")
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_scope(other)

    def test_unscoped_access_is_rejected(self):
        with self.assertRaises(ScopeMismatchError):
            self.ref.require_scope(None)

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
