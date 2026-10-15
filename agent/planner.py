"""Bounded LLM requests with exponential backoff and JSON parsing."""
import json
import random
import asyncio
import httpx
from urllib.parse import quote
from .config import get_prompt

def json_object(text):
    text=text.strip()
    fence=chr(96)*3
    if text.startswith(fence):
        text="\n".join(text.splitlines()[1:-1])
    result=json.loads(text)
    if not isinstance(result,dict): raise ValueError("JSON object required")
    return result

class LLM:
    def __init__(self,settings):
        self.settings=settings
    async def ask(self,system,content):
        s=self.settings
        if not s.api_key or not s.model:
            raise RuntimeError("Set OPENAI_MODEL and OPENAI_API_KEY")
        payload={"model":s.model,"temperature":0.1,
            "messages":[{"role":"system","content":system},{"role":"user","content":content}],
            "response_format":{"type":"json_object"}}
        async with httpx.AsyncClient(timeout=s.llm_timeout,follow_redirects=False) as client:
            for attempt in range(s.retries+1):
                try:
                    response=await client.post(s.base_url+"/chat/completions",
                        headers={"Authorization":"Bearer "+s.api_key},json=payload)
                    if response.status_code in (429,500,502,503,504) and attempt<s.retries:
                        retry=response.headers.get("retry-after","")
                        delay=float(retry) if retry.replace(".","",1).isdigit() else 2**attempt+random.random()
                        await asyncio.sleep(min(60,delay))
                        continue
                    response.raise_for_status()
                    return json_object(response.json()["choices"][0]["message"]["content"])
                except (httpx.TimeoutException,httpx.TransportError):
                    if attempt>=s.retries: raise
                    await asyncio.sleep(min(30,2**attempt+random.random()))
        raise RuntimeError("LLM request failed")

async def plan(llm,target,max_pages):
    if target.startswith(("https://","http://")):
        seed=[target]
    elif " " not in target and "@" not in target and "/" not in target:
        seed=["https://github.com/"+quote(target,safe="")]
    else:
        seed=["https://www.bing.com/search?q="+quote(target,safe="")]
    result=await llm.ask(get_prompt("planner"),json.dumps({
        "target":target,"seed_urls":seed,"max_pages":max_pages},ensure_ascii=False))
    options=result.get("urls",[])
    if not isinstance(options,list): raise ValueError("Expected urls array")
    out=[]
    for url in seed+options:
        if isinstance(url,str) and url not in out and len(url)<=2048:
            out.append(url)
    return out[:max_pages]
