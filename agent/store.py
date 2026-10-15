"""SQLite-backed targets, raw evidence, resolved profiles and event history."""
import csv
import io
import json
import sqlite3
import threading
from uuid import uuid4
from datetime import datetime,timezone

FIELDS=("names","emails","phones","locations","work","education",
        "socials","interests","relations","sources","conflicts","raw_snippets")
META=("derived","method","facts","preferred","derived_facts")

def now():
    return datetime.now(timezone.utc).isoformat()

def new_profile():
    return dict(id=str(uuid4()),names=[],handles={"telegram":"","github":"","vk":"","x":""},
                emails=[],phones=[],locations=[],work=[],education=[],socials=[],
                interests=[],relations=[],sources=[],conflicts=[],raw_snippets=[],
                derived=False,method="source",facts=[],preferred={},derived_facts=[])

def _key(value,field):
    if field=="sources" and isinstance(value,dict):
        return value.get("url","").rstrip("/").casefold()
    return json.dumps(value,sort_keys=True,ensure_ascii=False)

def _merge_source(existing,incoming):
    data=json.loads(json.dumps(existing,ensure_ascii=False))
    for field in FIELDS:
        if field=="conflicts":
            data[field]=data.get(field,[])+[v for v in incoming.get(field,[])
                if v not in data.get(field,[])]
            continue
        have={_key(v,field) for v in data.get(field,[])}
        for value in incoming.get(field,[]):
            if _key(value,field) not in have:
                data[field].append(value)
                have.add(_key(value,field))
    for platform,value in incoming.get("handles",{}).items():
        if platform in data["handles"] and value and not data["handles"][platform]:
            data["handles"][platform]=value
    data.setdefault("facts",[])
    for fact in incoming.get("facts",[]):
        if fact not in data["facts"]: data["facts"].append(fact)
    return data

class Store:
    def __init__(self,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        with self.lock,self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS targets
                (id TEXT PRIMARY KEY,value TEXT NOT NULL UNIQUE COLLATE NOCASE,
                 status TEXT NOT NULL,error TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles
                (id TEXT PRIMARY KEY,target_id TEXT UNIQUE NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_records
                (target_id TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS logs
                (id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT NOT NULL,
                 level TEXT NOT NULL,msg TEXT NOT NULL);
                INSERT OR IGNORE INTO source_records(target_id,data)
                    SELECT target_id,data FROM profiles;
            """)
    def add_target(self,value):
        value=value.strip()
        if not 1<=len(value)<=500: raise ValueError("Invalid target")
        with self.lock,self.db:
            self.db.execute("INSERT OR IGNORE INTO targets VALUES(?,?,?,?)",
                            (str(uuid4()),value,"pending",""))
            return dict(self.db.execute("SELECT * FROM targets WHERE value=?",(value,)).fetchone())
    def targets(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM targets ORDER BY rowid DESC")]
    def target(self,identifier):
        with self.lock:
            row=self.db.execute("SELECT * FROM targets WHERE id=?",(identifier,)).fetchone()
            return dict(row) if row else None
    def edit_target(self,identifier,value):
        value=value.strip()
        if not 1<=len(value)<=500: raise ValueError("Invalid target")
        with self.lock,self.db:
            return bool(self.db.execute("UPDATE targets SET value=?,status='pending',error='' WHERE id=?",
                                        (value,identifier)).rowcount)
    def target_status(self,identifier,status,error=""):
        if status not in ("pending","running","done","error"): raise ValueError("Invalid status")
        with self.lock,self.db:
            self.db.execute("UPDATE targets SET status=?,error=? WHERE id=?",
                            (status,error[:500],identifier))
    def delete_targets(self,identifiers):
        with self.lock,self.db:
            total=0
            for identifier in identifiers:
                self.db.execute("DELETE FROM source_records WHERE target_id=?",(identifier,))
                total+=self.db.execute("DELETE FROM targets WHERE id=?",(identifier,)).rowcount
            return total
    def source_records(self):
        with self.lock:
            return [(row["target_id"],json.loads(row["data"])) for row in
                    self.db.execute("SELECT target_id,data FROM source_records ORDER BY rowid")]
    def profiles(self):
        with self.lock:
            return [json.loads(row[0]) for row in
                    self.db.execute("SELECT data FROM profiles ORDER BY rowid")]
    def profile(self,identifier):
        with self.lock:
            row=self.db.execute("SELECT data FROM profiles WHERE id=?",(identifier,)).fetchone()
            return json.loads(row[0]) if row else None
    def upsert(self,target_id,profile):
        with self.lock,self.db:
            row=self.db.execute("SELECT data FROM source_records WHERE target_id=?",
                                (target_id,)).fetchone()
            if row:
                profile=_merge_source(json.loads(row[0]),profile)
            payload=json.dumps(profile,ensure_ascii=False)
            self.db.execute("INSERT INTO source_records VALUES(?,?) ON CONFLICT(target_id) DO UPDATE SET data=excluded.data",
                            (target_id,payload))
            self.db.execute("INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(target_id) DO UPDATE SET data=excluded.data",
                            (profile["id"],target_id,payload))
            return profile
    def replace_resolved(self,clusters):
        with self.lock,self.db:
            self.db.execute("DELETE FROM profiles")
            for target_id,profile in clusters:
                self.db.execute("INSERT INTO profiles VALUES(?,?,?)",
                    (profile["id"],target_id,json.dumps(profile,ensure_ascii=False)))
    def log(self,level,msg):
        item={"ts":now(),"level":level,"msg":str(msg)[:4000]}
        with self.lock,self.db:
            self.db.execute("INSERT INTO logs(ts,level,msg) VALUES(?,?,?)",
                            (item["ts"],item["level"],item["msg"]))
        return item
    def logs(self,limit=500):
        with self.lock:
            return [dict(r) for r in reversed(self.db.execute(
                "SELECT ts,level,msg FROM logs ORDER BY id DESC LIMIT ?",
                (max(1,min(limit,5000)),)).fetchall())]
    def counts(self):
        with self.lock:
            groups={r[0]:r[1] for r in self.db.execute(
                "SELECT status,COUNT(*) FROM targets GROUP BY status")}
            count=self.db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            return {"targets":sum(groups.values()),"processed":groups.get("done",0),
                    "profiles":count,"errors":groups.get("error",0)}
    def csv_export(self,profiles):
        stream=io.StringIO()
        columns=("id",)+FIELDS+("handles",)+META
        writer=csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader()
        for p in profiles:
            writer.writerow({k:json.dumps(p.get(k),ensure_ascii=False) for k in columns})
        return stream.getvalue()
