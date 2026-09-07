import unittest

from workflow_os.project_memory import ProjectMemoryError, ProjectMemoryStore
from workflow_os.project_scope import ProjectScope, ScopedAccessContext, ScopeMismatchError


class ProjectMemoryTests(unittest.TestCase):
    def setUp(self):
        self.scope = ProjectScope(chat_id="chat-1", project_id="project-a", repo_scope="owner/repo")
        self.context = ScopedAccessContext(scope=self.scope, state_epoch=7)
        self.store = ProjectMemoryStore()

    def test_exact_scope_and_epoch_can_read(self):
        self.store.put_project(context=self.context, key="plan", value={"step": 1})
        self.assertEqual(self.store.get_project(context=self.context, key="plan"), {"step": 1})

    def test_epoch_change_makes_old_memory_inaccessible(self):
        self.store.put_project(context=self.context, key="plan", value="old")
        newer = ScopedAccessContext(scope=self.scope, state_epoch=8)
        self.assertIsNone(self.store.get_project(context=newer, key="plan"))
        self.assertFalse(self.store.delete_project(context=newer, key="plan"))
        self.assertEqual(self.store.get_project(context=self.context, key="plan"), "old")

    def test_cross_scope_memory_does_not_leak(self):
        self.store.put_project(context=self.context, key="secret", value="a")
        variants = [
            ProjectScope(chat_id="chat-2", project_id="project-a", repo_scope="owner/repo"),
            ProjectScope(chat_id="chat-1", project_id="project-b", repo_scope="owner/repo"),
            ProjectScope(chat_id="chat-1", project_id="project-a", repo_scope="owner/other"),
        ]
        for scope in variants:
            with self.subTest(scope=scope):
                other = ScopedAccessContext(scope=scope, state_epoch=7)
                self.assertIsNone(self.store.get_project(context=other, key="secret"))

    def test_project_access_requires_explicit_context(self):
        with self.assertRaises(ScopeMismatchError):
            self.store.put_project(context=None, key="x", value=1)
        with self.assertRaises(ScopeMismatchError):
            self.store.get_project(context=None, key="x")

    def test_normal_non_project_chat_still_works(self):
        self.store.put_chat(chat_id="ordinary-chat", key="preference", value={"tone": "brief"})
        self.assertEqual(
            self.store.get_chat(chat_id="ordinary-chat", key="preference"),
            {"tone": "brief"},
        )

    def test_delete_is_preservation_safe(self):
        self.store.put_project(context=self.context, key="same", value="epoch-7")
        newer = ScopedAccessContext(scope=self.scope, state_epoch=8)
        self.store.put_project(context=newer, key="same", value="epoch-8")
        self.assertTrue(self.store.delete_project(context=newer, key="same"))
        self.assertEqual(self.store.get_project(context=self.context, key="same"), "epoch-7")
        self.assertIsNone(self.store.get_project(context=newer, key="same"))

    def test_global_distilled_rejects_project_specific_learning(self):
        with self.assertRaises(PermissionError):
            self.store.put_global_distilled(key="lesson", value="private", project_specific=True)
        self.store.put_global_distilled(key="lesson", value="generic", project_specific=False)
        self.assertEqual(self.store.get_global_distilled(key="lesson"), "generic")

    def test_values_are_defensively_copied(self):
        value = {"items": [1]}
        self.store.put_project(context=self.context, key="copy", value=value)
        value["items"].append(2)
        fetched = self.store.get_project(context=self.context, key="copy")
        self.assertEqual(fetched, {"items": [1]})
        fetched["items"].append(3)
        self.assertEqual(self.store.get_project(context=self.context, key="copy"), {"items": [1]})

    def test_corrupt_backend_entry_fails_closed(self):
        backend = {}
        store = ProjectMemoryStore(backend)
        storage_key = store._project_key(self.context, "bad")
        backend[storage_key] = {"value": "not-a-bound-record"}
        with self.assertRaises(ProjectMemoryError):
            store.get_project(context=self.context, key="bad")


if __name__ == "__main__":
    unittest.main()
