"""Export JSON/HTML dossiers and typed networkx graph edges."""
import html
import json
from urllib.parse import urlsplit
import networkx as nx

from .resolve import normalize, normalize_name

def _attributes(profile):
    n=normalize(profile)["_normalized"]
    identity={"email:"+x for x in n["emails"]}
    identity.update("phone:"+x for x in n["phones"])
    identity.update("handle:"+k+":"+v for k,v in n["handles"].items() if v)
    domains={"domain:"+x.split("@",1)[1] for x in n["emails"]}
    for social in profile.get("socials",[]):
        if isinstance(social,dict):
            domain=urlsplit(social.get("url","")).hostname
            if domain: domains.add("domain:"+domain.casefold())
    organizations={"organization:"+normalize_name(x) for x in profile.get("work",[])
                   if isinstance(x,str) and normalize_name(x)}
    locations={"city:"+x for x in n["locations"] if x}
    return identity,domains | organizations | locations

def build_graph(profiles):
    graph=nx.Graph()
    records=list(profiles)
    for row in records:
        name=row.get("names",[])
        graph.add_node(row["id"],label=name[0] if name else row["id"][:8])
    attributes=[_attributes(p) for p in records]
    for i,left in enumerate(records):
        for j in range(i+1,len(records)):
            right=records[j]
            identities=attributes[i][0] & attributes[j][0]
            associates=attributes[i][1] & attributes[j][1]
            if len(identities)>=2:
                graph.add_edge(left["id"],right["id"],type="same_person",
                    weight=len(identities),evidence=sorted(identities))
            elif len(associates)>=2:
                graph.add_edge(left["id"],right["id"],type="associate",
                    weight=len(associates),evidence=sorted(associates))
    return graph

def graph_data(rows):
    graph=build_graph(rows)
    return {"nodes":[{"id":key,**meta} for key,meta in graph.nodes(data=True)],
            "edges":[{"from":a,"to":b,**meta} for a,b,meta in graph.edges(data=True)]}

def save_reports(rows,folder):
    folder.mkdir(parents=True,exist_ok=True)
    for row in rows:
        body=json.dumps(row,ensure_ascii=False,indent=2)
        (folder/(row["id"]+".json")).write_text(body,encoding="utf-8")
        (folder/(row["id"]+".html")).write_text(
            "<meta charset='utf-8'><pre>"+html.escape(body)+"</pre>",encoding="utf-8")
    (folder/"profiles.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder/"graph.json").write_text(json.dumps(graph_data(rows),ensure_ascii=False,indent=2),encoding="utf-8")
