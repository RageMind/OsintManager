"""Offline SQLite and ASGI API regression tests."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from agent.store import Store,new_profile

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/"store.sqlite3")
    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_targets_and_counts(self):
        first=self.store.add_target("https://github.com/python")
        second=self.store.add_target("https://github.com/python")
        self.assertEqual(first["id"],second["id"])
        self.store.target_status(first["id"],"done")
        self.assertEqual(self.store.counts()["processed"],1)
        self.assertEqual(self.store.delete_targets([first["id"]]),1)
        self.assertEqual(self.store.counts()["targets"],0)

    def test_profile_update_preserves_identifier(self):
        item=self.store.add_target("project-alpha")
        p=new_profile()
        p["names"]=["Project Alpha"]
        p["sources"]=[{"url":"https://github.com/python","fetched_at":"2026-01-01","confidence":0.8}]
        first=self.store.upsert(item["id"],p)
        again=new_profile()
        again["names"]=["Project Alpha"]
        again["sources"]=[{"url":"https://github.com/python","fetched_at":"2026-01-01","confidence":0.8}]
        second=self.store.upsert(item["id"],again)
        self.assertEqual(first["id"],second["id"])
        self.assertEqual(len(self.store.profiles()),1)
        self.assertEqual(len(second["names"]),1)
        self.assertIn("Project Alpha",self.store.csv_export(self.store.profiles()))

    def test_rejected_empty_target(self):
        with self.assertRaises(ValueError): self.store.add_target(" ")

class ApiTests(unittest.TestCase):
    def test_local_state_and_authorization(self):
        from agent.controller import Controller
        from agent.api import create_app
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{"DATABASE_PATH":str(Path(folder)/"test.db"),"APP_TOKEN":"unit-test-token"}):
                controller=Controller()
                async def exercise():
                    transport=httpx.ASGITransport(app=create_app(controller))
                    async with httpx.AsyncClient(transport=transport,base_url="http://test") as client:
                        self.assertEqual((await client.get("/api/state")).status_code,401)
                        headers={"Authorization":"Bearer unit-test-token"}
                        self.assertEqual((await client.get("/api/state",headers=headers)).status_code,200)
                        response=await client.post("/api/targets",json={"value":"project-alpha"},headers=headers)
                        self.assertEqual(response.status_code,200)
                        self.assertEqual(len((await client.get("/api/targets",headers=headers)).json()),1)
                asyncio.run(exercise())
                controller.store.db.close()

if __name__=="__main__":
    unittest.main()
