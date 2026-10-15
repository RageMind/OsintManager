"""Convert text-extraction output into typed records."""
import json
from .store import new_profile, now
from .config import get_prompt

async def extract(llm, target, page):
    data = await llm.ask(get_prompt("extractor"), json.dumps({"label": target, "page": page}, ensure_ascii=False))
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    out = new_profile()
    for field in ("names", "work", "education", "interests", "raw_snippets"):
        values = data.get(field, [])
        if isinstance(values, list):
            out[field] = [x[:300] for x in values[:25] if isinstance(x, str)]
    out["sources"] = [{"url": page["url"], "fetched_at": now(), "confidence": 0.5}]
    return out
