"""Five malformed extractor responses and one-retry recovery without LLM/network."""
import asyncio
import json
import os
from unittest.mock import patch

import pytest

from agent.extractor import InvalidExtraction,extract
from agent.controller import Controller

PAGE={"url":"https://github.com/team","text":"Иванов. Email owner@example.org.","title":"Team"}

class FakeLLM:
    def __init__(self,responses):
        self.responses=list(responses)
        self.calls=[]
    async def ask(self,system,body):
        self.calls.append(system)
        value=self.responses[min(len(self.calls)-1,len(self.responses)-1)]
        if isinstance(value,Exception): raise value
        return value

@pytest.mark.parametrize(("value","retry"),[
    ("not JSON",True),
    ('["Ivanov"]',True),
    ({"names":"Иванов"},False),
    (None,True),
    ({},False),
])
def test_five_invalid_shapes_are_safe(value,retry):
    response={"names":["Иванов"],"emails":["owner@example.org"]}
    llm=FakeLLM([value,response])
    item=asyncio.run(extract(llm,"project",PAGE))
    if retry:
        assert len(llm.calls)==2
        assert "Return one valid JSON object" in llm.calls[1]
        assert item["emails"]==["owner@example.org"]
    else:
        assert len(llm.calls)==1
        assert item["names"]==[]

def test_invalid_json_is_retried_once_then_raises():
    llm=FakeLLM(["totally invalid"]*3)
    with pytest.raises(InvalidExtraction):
        asyncio.run(extract(llm,"project",PAGE))
    assert len(llm.calls)==2

def test_invalid_source_is_logged_and_next_source_processed(tmp_path):
    async def plan(llm,target,max_pages):
        return ["https://github.com/bad","https://github.com/good"]
    async def fetch(url,settings):
        return {"url":url,"title":"Demo","text":"Email owner@example.org."}
    class LLM:
        async def ask(self,system,body):
            if json.loads(body)["page"]["url"].endswith("/bad"):
                return "invalid json"
            return {"emails":["owner@example.org"]}
    env={"DATABASE_PATH":str(tmp_path/"store.db"),"REPORT_DIR":str(tmp_path/"reports"),
         "OSINT_DELAY":"0.001"}
    with patch.dict(os.environ,env),patch("agent.osint.plan",new=plan),\
         patch("agent.osint.fetch_with_retry",new=fetch):
        ctrl=Controller()
        ctrl.llm=LLM()
        ctrl.store.add_target("https://github.com/demo")
        async def job():
            await ctrl.start("osint")
            await ctrl.task
        asyncio.run(job())
        assert ctrl.state=="idle"
        assert ctrl.store.counts()["processed"]==1
        assert any(log["level"]=="WARN" and "/bad" in log["msg"] for log in ctrl.store.logs())
        assert len(ctrl.store.profiles())==1
        ctrl.store.db.close()
