"""Offline full-OSINT integration using a mocked language model and browser."""
import asyncio
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.controller import Controller
from agent.api import create_app

class FakeLLM:
    async def ask(self,system,content):
        return {"names":[],"emails":["public+tag@example.org"],
                "phones":[],"locations":[],"work":[],"education":[],
                "interests":[],"raw_snippets":[]}

async def fake_plan(client,target,max_pages):
    return [target]

async def fake_fetch(url,settings):
    return {"url":url,"title":"Authorized source",
            "text":"Public project email: public+tag@example.org"}

def test_two_targets_one_profile_without_network(tmp_path):
    env={"DATABASE_PATH":str(tmp_path/"app.sqlite3"),
         "REPORT_DIR":str(tmp_path/"reports"),"OSINT_DELAY":"0.001",
         "OSINT_RESOLVE_THRESHOLD":"0.75"}
    with patch.dict(os.environ,env),patch("agent.osint.plan",new=fake_plan),\
         patch("agent.osint.fetch_with_retry",new=fake_fetch):
        ctrl=Controller()
        ctrl.llm=FakeLLM()
        ctrl.store.add_target("https://github.com/project-one")
        ctrl.store.add_target("https://github.com/project-two")
        async def run():
            await ctrl.start(mode="osint")
            await ctrl.task
        asyncio.run(run())
        profiles=ctrl.store.profiles()
        assert len(profiles)==1
        assert ctrl.store.counts()["processed"]==2
        assert profiles[0]["emails"]==["public+tag@example.org"]
        assert len(profiles[0]["facts"])>=2
        assert all(f["source"] and f["fetched_at"] for f in profiles[0]["facts"])
        assert (Path(env["REPORT_DIR"])/"graph.json").exists()
        with TestClient(create_app(ctrl)) as browser:
            response=browser.get("/api/graph")
            assert response.status_code==200
            assert response.json()["nodes"][0]["id"]==profiles[0]["id"]
        ctrl.store.db.close()
