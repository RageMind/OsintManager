"""Offline pipeline through fake HTML/httpx/Playwright and model responses."""
import asyncio
import json
import os
from unittest.mock import patch

import httpx

from agent import executor,osint
from agent.controller import Controller

HTML={
    "/research-one":"<html><head><title>Research One</title></head><body>Public author Ivanov Ivan. Contact owner+lab@example.org.</body></html>",
    "/research-two":"<html><head><title>Research Two</title></head><body>Ivanov Ivan published a paper. Contact owner+lab@example.org.</body></html>",
}

class OfflineLLM:
    async def ask(self,system,body):
        page=json.loads(body)["page"]
        return {"names":["Ivanov Ivan"],"emails":["owner+lab@example.org"],
                "work":[],"education":[],"interests":[],"raw_snippets":[]}

class NoBrowser:
    async def __aenter__(self):
        raise OSError("Chromium unavailable in offline test")
    async def __aexit__(self,*args):
        return False

def test_full_pipeline_with_html_and_persistent_dedup(tmp_path,monkeypatch):
    original_client=httpx.AsyncClient
    requests=[]
    def handler(request):
        requests.append(str(request.url))
        if request.url.path=="/robots.txt":
            return httpx.Response(200,text="User-agent: *\nAllow: /\n")
        if request.url.path in HTML:
            return httpx.Response(200,text=HTML[request.url.path],
                                  headers={"content-type":"text/html"})
        return httpx.Response(404)
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(executor.httpx,"AsyncClient",
        lambda **kwargs:original_client(transport=transport,**kwargs))
    monkeypatch.setattr(executor,"async_playwright",lambda:NoBrowser())
    async def check(url,settings):
        assert url.startswith("https://github.com/")
        return url
    monkeypatch.setattr(executor,"check_url",check)
    original_resolve=osint.resolve_all
    calls=[]
    def spy(store,threshold):
        calls.append(threshold)
        return original_resolve(store,threshold)
    monkeypatch.setattr(osint,"resolve_all",spy)
    env={"DATABASE_PATH":str(tmp_path/"agent.sqlite3"),
         "REPORT_DIR":str(tmp_path/"reports"),"OSINT_DELAY":"0.001",
         "OSINT_DOMAIN_RPS":"20","OSINT_RESOLVE_THRESHOLD":"0.75"}
    with patch.dict(os.environ,env):
        ctrl=Controller()
        ctrl.llm=OfflineLLM()
        ctrl.store.add_target("https://github.com/research-one")
        ctrl.store.add_target("https://github.com/research-two")
        async def run():
            await ctrl.start("osint")
            await ctrl.task
        asyncio.run(run())
        first=ctrl.store.profiles()
        assert ctrl.state=="idle"
        assert len(first)==1
        identifier=first[0]["id"]
        assert len(ctrl.store.source_records())==2
        assert len(first[0]["sources"])==2
        assert all(f["source"] and f["fetched_at"] for f in first[0]["facts"])
        assert len(calls)==1
        assert requests.count("https://github.com/robots.txt")==1
        assert (tmp_path/"reports"/"profiles.json").exists()
        asyncio.run(run())
        second=ctrl.store.profiles()
        assert len(second)==1
        assert second[0]["id"]==identifier
        assert len(ctrl.store.source_records())==2
        assert len(calls)==2
        assert ctrl.store.counts()["processed"]==2
        assert len(second[0]["sources"])==2
        ctrl.store.db.close()
