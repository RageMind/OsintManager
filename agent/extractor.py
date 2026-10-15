"""Convert public-source extraction into evidence-bearing records."""
import json
from .store import new_profile, now
from .config import get_prompt

async def extract(llm,target,page):
    data=await llm.ask(get_prompt("extractor"),json.dumps({
        "label":target,"page":page},ensure_ascii=False))
    if not isinstance(data,dict): raise ValueError("Expected JSON object")
    out=new_profile()
    timestamp=now()
    for field in ("names","work","education","interests","raw_snippets"):
        values=data.get(field,[])
        if not isinstance(values,list): continue
        out[field]=[value[:300] for value in values[:25] if isinstance(value,str)]
        for value in out[field]:
            out["facts"].append({"field":field,"value":value,
                "source":page["url"],"fetched_at":timestamp,
                "confidence":0.5,"derived":False,"method":"source"})
    out["sources"]=[{"url":page["url"],"fetched_at":timestamp,"confidence":0.5}]
    return out
