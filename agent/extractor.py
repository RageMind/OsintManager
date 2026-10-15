"""Extract page-supported public facts with per-field provenance."""
import json
import re
from urllib.parse import urlsplit

from .store import new_profile,now
from .config import get_prompt

TEXT_FIELDS=("names","emails","phones","locations","work",
             "education","interests","raw_snippets")
HANDLE_FIELDS=("telegram","github","vk","x")

def on_page(value,page):
    candidate=str(value).strip().casefold()
    body=page.get("text","").casefold()
    url=page.get("url","").casefold()
    return bool(candidate) and (candidate in body or candidate in url)

async def extract(llm,target,page):
    data=await llm.ask(get_prompt("extractor"),json.dumps({
        "label":target,"page":page},ensure_ascii=False))
    if not isinstance(data,dict): raise ValueError("Expected JSON object")
    out=new_profile()
    timestamp=now()
    def add_fact(field,value):
        out["facts"].append({"field":field,"value":value,
            "source":page["url"],"fetched_at":timestamp,
            "confidence":0.5,"derived":False,"method":"source"})
    for field in TEXT_FIELDS:
        values=data.get(field,[])
        if not isinstance(values,list): continue
        for value in values[:25]:
            if not isinstance(value,str) or not on_page(value,page): continue
            value=value[:300].strip()
            if field=="emails" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",value): continue
            if field=="phones" and len(re.sub(r"\D","",value)) not in range(8,16): continue
            if field=="locations" and len(value)>100: continue
            if value not in out[field]:
                out[field].append(value)
                add_fact(field,value)
    handles=data.get("handles",{})
    if isinstance(handles,dict):
        for platform in HANDLE_FIELDS:
            value=handles.get(platform,"")
            if isinstance(value,str) and len(value)<=100 and on_page(value,page):
                out["handles"][platform]=value.strip()
                add_fact("handles."+platform,value.strip())
    socials=data.get("socials",[])
    if isinstance(socials,list):
        for item in socials[:25]:
            if not isinstance(item,dict): continue
            url=item.get("url","")
            if not isinstance(url,str) or urlsplit(url).scheme!="https": continue
            if not on_page(url,page): continue
            record={"platform":str(item.get("platform",""))[:50],
                "url":url[:2048],"bio":str(item.get("bio",""))[:300]}
            if record not in out["socials"]:
                out["socials"].append(record)
                add_fact("socials",record)
    out["sources"]=[{"url":page["url"],"fetched_at":timestamp,"confidence":0.5}]
    return out
