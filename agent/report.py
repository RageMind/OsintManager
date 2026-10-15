"""Export local research reports."""
import json
import html
import networkx as nx

def graph_data(rows):
    g=nx.Graph()
    for row in rows:
        g.add_node(row["id"],label=(row["names"][0] if row["names"] else row["id"][:8]))
    return {"nodes":[{"id":key,**meta} for key,meta in g.nodes(data=True)],"edges":[]}

def save_reports(rows,folder):
    folder.mkdir(parents=True,exist_ok=True)
    for row in rows:
        body=json.dumps(row,ensure_ascii=False,indent=2)
        (folder/(row["id"]+".json")).write_text(body,encoding="utf-8")
        (folder/(row["id"]+".html")).write_text("<meta charset='utf-8'><pre>"+html.escape(body)+"</pre>",encoding="utf-8")
    (folder/"profiles.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    (folder/"graph.json").write_text(json.dumps(graph_data(rows),ensure_ascii=False),encoding="utf-8")
