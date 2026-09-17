import unittest

from workflow_os.project_context import ProjectContextError, ProjectContextStore
from workflow_os.project_scope import ProjectScope, ScopedAccessContext, ScopeMismatchError


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.scope = ProjectScope(chat_id="chat-1", project_id="project-a", repo_scope="owner/repo")
        self.context = ScopedAccessContext(scope=self.scope, state_epoch=7)
        self.store = ProjectContextStore()

    def test_exact_scope_and_epoch_can_read(self):
        self.store.put(context=self.context, key="snapshot", value={"files": ["a.py"]})
        self.assertEqual(self.store.get(context=self.context, key="snapshot"), {"files": ["a.py"]})

    def test_epoch_change_makes_old_context_inaccessible(self):
        self.store.put(context=self.context, key="snapshot", value="old")
        newer = ScopedAccessContext(scope=self.scope, state_epoch=8)
        self.assertIsNone(self.store.get(context=newer, key="snapshot"))
        self.assertFalse(self.store.delete(context=newer, key="snapshot"))
        self.assertEqual(self.store.get(context=self.context, key="snapshot"), "old")

    def test_cross_scope_context_does_not_leak(self):
        self.store.put(context=self.context, key="snapshot", value="private")
        variants = [
            ProjectScope(chat_id="chat-2", project_id="project-a", repo_scope="owner/repo"),
            ProjectScope(chat_id="chat-1", project_id="project-b", repo_scope="owner/repo"),
            ProjectScope(chat_id="chat-1", project_id="project-a", repo_scope="owner/other"),
        ]
        for scope in variants:
            with self.subTest(scope=scope):
                other = ScopedAccessContext(scope=scope, state_epoch=7)
                self.assertIsNone(self.store.get(context=other, key="snapshot"))

    def test_access_requires_explicit_context(self):
        with self.assertRaises(ScopeMismatchError):
            self.store.put(context=None, key="x", value=1)
        with self.assertRaises(ScopeMismatchError):
            self.store.get(context=None, key="x")

    def test_delete_is_preservation_safe(self):
        self.store.put(context=self.context, key="same", value="epoch-7")
        newer = ScopedAccessContext(scope=self.scope, state_epoch=8)
        self.store.put(context=newer, key="same", value="epoch-8")
        self.assertTrue(self.store.delete(context=newer, key="same"))
        self.assertEqual(self.store.get(context=self.context, key="same"), "epoch-7")
        self.assertIsNone(self.store.get(context=newer, key="same"))

    def test_values_are_defensively_copied(self):
        value = {"files": ["a.py"]}
        self.store.put(context=self.context, key="copy", value=value)
        value["files"].append("b.py")
        fetched = self.store.get(context=self.context, key="copy")
        self.assertEqual(fetched, {"files": ["a.py"]})
        fetched["files"].append("c.py")
        self.assertEqual(self.store.get(context=self.context, key="copy"), {"files": ["a.py"]})

    def test_corrupt_backend_entry_fails_closed(self):
        backend = {}
        store = ProjectContextStore(backend)
        storage_key = store._storage_key(self.context, "bad")
        backend[storage_key] = {"value": "unbound"}
        with self.assertRaises(ProjectContextError):
            store.get(context=self.context, key="bad")


if __name__ == "__main__":
    unittest.main()
