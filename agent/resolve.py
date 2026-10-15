"""Conservative entity resolution with source-level provenance."""
from __future__ import annotations
import copy
import json
import re
import unicodedata
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .store import FIELDS, new_profile

CYR = {
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh",
    "з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o",
    "п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts",
    "ч":"ch","ш":"sh","щ":"shch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
}

def normalize_name(value):
    value=unicodedata.normalize("NFKC",str(value)).casefold()
    value="".join(CYR.get(c,c) for c in value)
    return " ".join(re.sub(r"[^a-z0-9\s-]"," ",value).split())

def normalize_email(value):
    value=str(value).strip().casefold()
    if value.count("@")!=1: return ""
    local,domain=value.split("@",1)
    local=local.split("+",1)[0]
    if not local or not domain or "." not in domain: return ""
    return local+"@"+domain

def normalize_phone(value):
    text=str(value).strip()
    if not text: return ""
    digits=re.sub(r"\D","",text)
    if not digits: return ""
    if len(digits)==11 and digits[0]=="8":
        digits="7"+digits[1:]
    elif len(digits)==10 and not text.startswith("+"):
        digits="7"+digits
    if not 8<=len(digits)<=15: return ""
    return "+"+digits

def canonical_url(value):
    try:
        p=urlsplit(str(value).strip())
        if p.scheme.lower() not in ("http","https") or not p.hostname: return ""
        port=(":"+str(p.port)) if p.port and p.port not in (80,443) else ""
        query=urlencode(sorted((k,v) for k,v in parse_qsl(p.query,keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in ("gclid","fbclid")))
        path=p.path.rstrip("/") or "/"
        return urlunsplit((p.scheme.lower(),p.hostname.lower()+port,path,query,""))
    except (ValueError,TypeError):
        return ""

def normalize(record):
    result=copy.deepcopy(record)
    result.setdefault("derived",False)
    result.setdefault("method","source")
    result.setdefault("facts",[])
    result.setdefault("socials",[])
    result.setdefault("handles",{})
    result.setdefault("sources",[])
    normalized={
        "names":[normalize_name(x) for x in result.get("names",[]) if isinstance(x,str)],
        "locations":[normalize_name(x) for x in result.get("locations",[]) if isinstance(x,str)],
        "emails":[x for v in result.get("emails",[]) if (x:=normalize_email(v))],
        "phones":[x for v in result.get("phones",[]) if (x:=normalize_phone(v))],
        "handles":{k:str(v).strip().lstrip("@").casefold() for k,v in result["handles"].items() if v},
        "urls":[x for v in result["socials"] if isinstance(v,dict) and (x:=canonical_url(v.get("url","")))],
    }
    result["_normalized"]=normalized
    source=result["sources"][0] if result["sources"] else {}
    existing={(f.get("field"),json.dumps(f.get("value"),sort_keys=True,ensure_ascii=False))
              for f in result["facts"] if isinstance(f,dict)}
    for field in FIELDS:
        if field in ("sources","conflicts"): continue
        for value in result.get(field,[]):
            marker=(field,json.dumps(value,sort_keys=True,ensure_ascii=False))
            if marker not in existing:
                result["facts"].append({"field":field,"value":copy.deepcopy(value),
                    "source":source.get("url",""),"fetched_at":source.get("fetched_at",""),
                    "confidence":float(source.get("confidence",0.5)),
                    "derived":False,"method":"source"})
                existing.add(marker)
    for field in ("names","emails","phones"):
        for original,canonical in zip(result.get(field,[]),normalized[field]):
            if original!=canonical:
                result["facts"].append({"field":field,"value":canonical,
                    "source":source.get("url",""),"fetched_at":source.get("fetched_at",""),
                    "confidence":float(source.get("confidence",0.5)),
                    "derived":True,"method":"normalize"})
    return result

def block_keys(record):
    n=record.get("_normalized") or normalize(record)["_normalized"]
    keys=set()
    for name in n["names"]:
        if name: keys.add("surname:"+name.split()[0][:3])
    for platform,handle in n["handles"].items():
        keys.add("handle:"+platform+":"+handle)
    for email in n["emails"]:
        keys.add("email:"+email)
        keys.add("domain:"+email.split("@",1)[1])
    for phone in n["phones"]:
        keys.add("phone:"+phone)
    return keys

def block_key(record):
    keys=block_keys(record)
    for prefix in ("surname:","handle:","domain:","email:","phone:"):
        matching=sorted(k for k in keys if k.startswith(prefix))
        if matching: return matching[0]
    return ""

def score_pair(a,b):
    a=a.get("_normalized") or normalize(a)["_normalized"]
    b=b.get("_normalized") or normalize(b)["_normalized"]
    if set(a["emails"]) & set(b["emails"]): return 1.0
    if set(a["phones"]) & set(b["phones"]): return 0.95
    if any(handle==b["handles"].get(platform) for platform,handle in a["handles"].items()):
        return 0.8
    if set(a["names"]) & set(b["names"]):
        if set(a["locations"]) & set(b["locations"]): return 0.6
        return 0.3
    return 0.0

def _confidence(record,field=None,value=None):
    if field is not None:
        facts=[f for f in record.get("facts",[]) if isinstance(f,dict)
               and f.get("field")==field and f.get("value")==value
               and not f.get("derived",False)]
        if facts:
            return max(float(f.get("confidence",0.5)) for f in facts)
    sources=record.get("sources",[])
    return max((float(s.get("confidence",0.5)) for s in sources),default=0.5)

def _evidence(record,field,value):
    matches=[f for f in record.get("facts",[]) if isinstance(f,dict)
             and f.get("field")==field and f.get("value")==value]
    if matches:
        return [{"url":f.get("source",""),"fetched_at":f.get("fetched_at","")}
                for f in matches]
    return record.get("sources",[])

def merge_cluster(records):
    if not records: raise ValueError("Empty cluster")
    records=[normalize(r) for r in records]
    best=max(records,key=_confidence)
    result=new_profile()
    result["id"]=records[0]["id"]
    result["derived"]=len(records)>1
    result["method"]="entity_resolution" if len(records)>1 else "source"
    result["facts"]=[]
    result["preferred"]={}
    seen={k:set() for k in FIELDS}
    for record in records:
        for key in FIELDS:
            for value in record.get(key,[]):
                signature=(canonical_url(value.get("url","")) if key=="sources" and isinstance(value,dict)
                           else json.dumps(value,sort_keys=True,ensure_ascii=False))
                if signature not in seen[key]:
                    result[key].append(copy.deepcopy(value))
                    seen[key].add(signature)
        for fact in record["facts"]:
            if fact not in result["facts"]: result["facts"].append(copy.deepcopy(fact))
    for platform in result["handles"]:
        options=[(r.get("handles",{}).get(platform,""),
                  _confidence(r,"handles."+platform,r.get("handles",{}).get(platform,"")),r) for r in records]
        options=[v for v in options if v[0]]
        if not options: continue
        options.sort(key=lambda x:-x[1])
        result["handles"][platform]=options[0][0]
        distinct={normalize_name(v[0]) for v in options}
        if len(distinct)>1:
            result["conflicts"].append({"field":"handles."+platform,"conflict":True,
                "values":[{"value":v,"confidence":confidence,
                           "sources":_evidence(r,"handles."+platform,v)} for v,confidence,r in options]})
    for field in ("names","locations","work","education"):
        options=[(value,_confidence(r,field,value),r) for r in records for value in r.get(field,[])]
        if not options: continue
        options.sort(key=lambda x:-x[1])
        result["preferred"][field]=options[0][0]
        if field in ("names","locations") and len({normalize_name(v[0]) for v in options})>1:
            result["conflicts"].append({"field":field,"conflict":True,
                "values":[{"value":v,"confidence":c,"sources":_evidence(r,field,v)}
                          for v,c,r in options]})
    result["derived_facts"]=[f for f in result["facts"] if f.get("derived")]
    return result

def resolve_all(store,threshold=None):
    from .config import Settings
    if threshold is None:
        threshold=Settings.load().resolve_threshold
    if not 0 < threshold <= 1: raise ValueError("Threshold must be in (0,1]")
    sources=store.source_records()
    rows=[normalize(data) for _,data in sources]
    parent=list(range(len(rows)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    candidates=defaultdict(set)
    for i,row in enumerate(rows):
        for key in block_keys(row):
            candidates[key].add(i)
    compared=set()
    for bucket in candidates.values():
        indices=sorted(bucket)
        for a_index,i in enumerate(indices):
            for j in indices[a_index+1:]:
                pair=(i,j)
                if pair in compared: continue
                compared.add(pair)
                if score_pair(rows[i],rows[j])>=threshold:
                    a,b=root(i),root(j)
                    if a!=b: parent[b]=a
    groups=defaultdict(list)
    for i in range(len(rows)):
        groups[root(i)].append(i)
    clusters=[]
    for indices in groups.values():
        combined=merge_cluster([sources[i][1] for i in indices])
        clusters.append((sources[indices[0]][0],combined))
    store.replace_resolved(clusters)
    return [p for _,p in clusters]
