"""SQLite-backed targets, source records and durable event history."""
import json
import sqlite3
import threading
import csv
import io
from uuid import uuid4
from datetime import datetime, timezone

FIELDS = ("names", "emails", "phones", "locations", "work", "education",
          "socials", "interests", "relations", "sources", "conflicts", "raw_snippets")

def now():
    return datetime.now(timezone.utc).isoformat()

def new_profile():
    return dict(id=str(uuid4()), names=[], handles={"telegram":"","github":"","vk":"","x":""},
                emails=[],phones=[],locations=[],work=[],education=[],socials=[],
                interests=[],relations=[],sources=[],conflicts=[],raw_snippets=[])

class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        with self.lock,self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS targets
                (id TEXT PRIMARY KEY,value TEXT NOT NULL UNIQUE COLLATE NOCASE,status TEXT NOT NULL,error TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles
                (id TEXT PRIMARY KEY,target_id TEXT UNIQUE NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS logs
                (id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT NOT NULL,level TEXT NOT NULL,msg TEXT NOT NULL);
            """)
    def add_target(self,value):
        value=value.strip()
        if not 1<=len(value)<=500: raise ValueError("Invalid target")
        with self.lock,self.db:
            self.db.execute("INSERT OR IGNORE INTO targets VALUES(?,?,?,?)",(str(uuid4()),value,"pending",""))
            return dict(self.db.execute("SELECT * FROM targets WHERE value=?",(value,)).fetchone())
    def targets(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM targets ORDER BY rowid DESC")]
    def target(self,identifier):
        with self.lock:
            row=self.db.execute("SELECT * FROM targets WHERE id=?",(identifier,)).fetchone()
            return dict(row) if row else None
    def edit_target(self,identifier,value):
        value=value.strip()
        if not 1<=len(value)<=500: raise ValueError("Invalid target")
        with self.lock,self.db:
            return bool(self.db.execute("UPDATE targets SET value=?,status='pending' WHERE id=?",
                      (value,identifier)).rowcount)
    def target_status(self,identifier,status,error=""):
        if status not in ("pending","running","done","error"): raise ValueError("Invalid status")
        with self.lock,self.db:
            self.db.execute("UPDATE targets SET status=?,error=? WHERE id=?",(status,error[:500],identifier))
    def delete_targets(self,identifiers):
        with self.lock,self.db:
            total=0
            for identifier in identifiers:
                total+=self.db.execute("DELETE FROM targets WHERE id=?",(identifier,)).rowcount
            return total
    def profiles(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM profiles ORDER BY rowid DESC")]
    def profile(self,identifier):
        with self.lock:
            row=self.db.execute("SELECT data FROM profiles WHERE id=?",(identifier,)).fetchone()
            return json.loads(row[0]) if row else None
    def upsert(self,target_id,profile):
        with self.lock,self.db:
            prior=self.db.execute("SELECT data FROM profiles WHERE target_id=?",(target_id,)).fetchone()
            if prior:
                existing=json.loads(prior[0])
                profile["id"]=existing["id"]
                for key in FIELDS:
                    if key=="conflicts": continue
                    seen={(v.get("url","").rstrip("/").lower() if key=="sources" and isinstance(v,dict) else json.dumps(v,sort_keys=True,ensure_ascii=False)) for v in existing[key]}
                    profile[key]=existing[key]+[v for v in profile[key]
                        if (v.get("url","").rstrip("/").lower() if key=="sources" and isinstance(v,dict) else json.dumps(v,sort_keys=True,ensure_ascii=False)) not in seen]
            self.db.execute("INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(target_id) DO UPDATE SET data=excluded.data",
                            (profile["id"],target_id,json.dumps(profile,ensure_ascii=False)))
            return profile
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
            groups={r[0]:r[1] for r in self.db.execute("SELECT status,COUNT(*) FROM targets GROUP BY status")}
            count=self.db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            return {"targets":sum(groups.values()),"processed":groups.get("done",0),
                    "profiles":count,"errors":groups.get("error",0)}
    def csv_export(self,profiles):
        stream=io.StringIO()
        writer=csv.DictWriter(stream,fieldnames=("id","names","handles","emails","phones","locations",
          "work","education","socials","interests","relations","sources","conflicts","raw_snippets"))
        writer.writeheader()
        for p in profiles:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) for k,v in p.items()})
        return stream.getvalue()
