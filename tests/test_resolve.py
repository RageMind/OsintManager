"""Offline normalization, score, clustering, evidence and graph tests."""
import pytest

from agent.resolve import (
    normalize,normalize_name,normalize_email,normalize_phone,canonical_url,
    block_key,score_pair,merge_cluster,resolve_all,
)
from agent.report import build_graph,graph_data
from agent.store import Store,new_profile

def record(name="",city="",email="",phone="",handle="",confidence=0.8):
    p=new_profile()
    if name:p["names"]=[name]
    if city:p["locations"]=[city]
    if email:p["emails"]=[email]
    if phone:p["phones"]=[phone]
    if handle:p["handles"]["github"]=handle
    p["sources"]=[{"url":"https://github.com/"+p["id"],
                   "fetched_at":"2026-10-15T00:00:00+00:00","confidence":confidence}]
    return p

def test_normalize():
    p=record("Иванов Иван","Москва","PERSON+News@Example.COM","8 (916) 123-45-67")
    normalized=normalize(p)["_normalized"]
    assert normalized["names"]==["ivanov ivan"]
    assert normalized["emails"]==["person@example.com"]
    assert normalized["phones"]==["+79161234567"]
    assert normalize_phone("+1 (212) 555-1212")=="+12125551212"
    assert normalize_name("Петров")=="petrov"
    assert normalize_email("A+B@EXAMPLE.org")=="a@example.org"
    assert canonical_url("https://Example.com/a/?utm_source=x&b=2#frag")=="https://example.com/a?b=2"
    assert block_key(p)=="surname:iva"
    assert p["emails"]==["PERSON+News@Example.COM"]
    derived=[f for f in normalize(p)["facts"] if f["derived"]]
    assert any(f["method"]=="normalize" and f["field"]=="emails" for f in derived)

@pytest.mark.parametrize(("left","right","expected"),[
    ({"email":"a+promo@test.org"},{"email":"A@test.org"},1.0),
    ({"phone":"8 (916) 111-22-33"},{"phone":"+79161112233"},0.95),
    ({"handle":"Example"},{"handle":"example"},0.8),
    ({"name":"Иванов Иван","city":"Москва"},{"name":"Ivanov Ivan","city":"Moskva"},0.6),
    ({"name":"Иванов Иван"},{"name":"Ivanov Ivan"},0.3),
    ({"name":"Иванов Иван"},{"name":"Петров Петр"},0.0),
])
def test_score_pair(left,right,expected):
    assert score_pair(record(**left),record(**right))==expected

def test_resolve_same_email(tmp_path):
    db=Store(tmp_path/"manager.sqlite3")
    t1=db.add_target("first")
    t2=db.add_target("second")
    a=record("Иванов Иван",email="owner+one@example.org",handle="first")
    b=record("Ivanov Ivan",email="OWNER@example.org",handle="second")
    db.upsert(t1["id"],a)
    db.upsert(t2["id"],b)
    result=resolve_all(db,0.75)
    assert len(result)==len(db.profiles())==1
    assert len(db.source_records())==2
    assert result[0]["id"]==a["id"]
    assert len(result[0]["sources"])==2
    assert len(result[0]["facts"])>=2
    assert resolve_all(db,0.75)[0]["id"]==a["id"]
    db.db.close()

def test_resolve_same_name_only_not_merged(tmp_path):
    db=Store(tmp_path/"manager.sqlite3")
    a=db.add_target("first")
    b=db.add_target("second")
    db.upsert(a["id"],record("Иванов Иван"))
    db.upsert(b["id"],record("Ivanov Ivan"))
    assert len(resolve_all(db,0.75))==2
    db.db.close()

def test_conflicting_values_retained():
    a=record("Иванов Иван",email="owner@example.org",handle="one",confidence=0.9)
    b=record("Ivanov Ivan",email="owner@example.org",handle="two",confidence=0.6)
    merged=merge_cluster([a,b])
    assert merged["handles"]["github"]=="one"
    conflicts=[c for c in merged["conflicts"] if c["field"]=="handles.github"]
    assert len(conflicts)==1
    assert {i["value"] for i in conflicts[0]["values"]}=={"one","two"}
    assert all(item["sources"] for item in conflicts[0]["values"])
    assert merged["preferred"]["names"]=="Иванов Иван"
    assert merged["derived"] is False

def test_graph_edges_types_not_combined():
    a=record("A",email="first@org.com",phone="+79161112233")
    b=record("B",email="first@org.com",phone="8 916 111 22 33")
    a["work"]=["Institute X"];b["work"]=["Institute X"]
    a["locations"]=["Moscow"];b["locations"]=["Moscow"]
    c=record("C",email="worker1@other.com")
    d=record("D",email="worker2@other.com")
    c["work"]=["Institute Y"];d["work"]=["Institute Y"]
    c["locations"]=["Kazan"];d["locations"]=["Kazan"]
    graph=build_graph([a,b,c,d])
    assert graph[a["id"]][b["id"]]["type"]=="same_person"
    assert graph[a["id"]][b["id"]]["weight"]==2
    assert graph[c["id"]][d["id"]]["type"]=="associate"
    assert graph[c["id"]][d["id"]]["weight"]==3
    assert len(graph.edges)==2
    assert {edge["type"] for edge in graph_data([a,b,c,d])["edges"]}=={"same_person","associate"}

def test_single_shared_association_is_not_edge():
    a=record("A",city="Kazan")
    b=record("B",city="Kazan")
    assert build_graph([a,b]).number_of_edges()==0
