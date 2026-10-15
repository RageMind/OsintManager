"""Authenticated FastAPI routes and real-time WebSocket event stream."""
import asyncio
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from .config import ROOT, PROMPTS, public_values, update, get_prompt, update_prompt
from .report import graph_data

def create_app(ctrl):
    if ctrl.settings.host not in ("127.0.0.1","::1","localhost") and not ctrl.settings.token:
        raise RuntimeError("APP_TOKEN is required when listening beyond localhost")
    app=FastAPI(title="OSINT Manager",docs_url=None,redoc_url=None)
    web=ROOT/"web"

    def authorized(request:Request):
        token=ctrl.settings.token
        if token and request.headers.get("authorization","")!="Bearer "+token:
            raise HTTPException(401,"Authorization required")

    @app.get("/api/state",dependencies=[Depends(authorized)])
    def state(): return ctrl.snapshot()

    @app.get("/api/targets",dependencies=[Depends(authorized)])
    def targets(): return ctrl.store.targets()

    @app.post("/api/targets",dependencies=[Depends(authorized)])
    async def add(request:Request):
        data=await request.json()
        try: return ctrl.store.add_target(data["value"])
        except (KeyError,ValueError) as exc: raise HTTPException(400,str(exc))

    @app.post("/api/targets/import",dependencies=[Depends(authorized)])
    async def import_targets(request:Request):
        data=await request.json()
        lines=data.get("lines",[])
        if not isinstance(lines,list) or len(lines)>1000:
            raise HTTPException(400,"Maximum 1000 entries")
        added=[]
        for line in lines:
            if isinstance(line,str) and line.strip() and not line.lstrip().startswith("#"):
                try: added.append(ctrl.store.add_target(line))
                except ValueError: continue
        return {"count":len(added)}

    @app.patch("/api/targets/{identifier}",dependencies=[Depends(authorized)])
    async def change(identifier:str,request:Request):
        data=await request.json()
        try: changed=ctrl.store.edit_target(identifier,data["value"])
        except (ValueError,KeyError) as exc: raise HTTPException(400,str(exc))
        if not changed: raise HTTPException(404,"Not found")
        return {"ok":True}

    @app.delete("/api/targets/{identifier}",dependencies=[Depends(authorized)])
    def delete(identifier:str):
        return {"deleted":ctrl.store.delete_targets([identifier])}

    @app.post("/api/targets/bulk",dependencies=[Depends(authorized)])
    async def bulk(request:Request):
        data=await request.json()
        ids=data.get("ids",[])
        if not isinstance(ids,list) or len(ids)>1000:
            raise HTTPException(400,"Invalid ids")
        return {"deleted":ctrl.store.delete_targets([x for x in ids if isinstance(x,str)])}

    @app.get("/api/profiles",dependencies=[Depends(authorized)])
    def profiles(): return ctrl.store.profiles()

    @app.get("/api/profiles/export",dependencies=[Depends(authorized)])
    def export(format:str="json",id:str=""):
        rows=[ctrl.store.profile(id)] if id else ctrl.store.profiles()
        rows=[p for p in rows if p]
        if id and not rows: raise HTTPException(404,"Profile not found")
        if format=="json":
            return Response(json.dumps(rows[0] if id else rows,ensure_ascii=False,indent=2),
                media_type="application/json",
                headers={"Content-Disposition":"attachment; filename=profiles.json"})
        if format=="csv":
            return Response(ctrl.store.csv_export(rows),media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition":"attachment; filename=profiles.csv"})
        raise HTTPException(400,"Unknown format")

    @app.get("/api/profiles/{identifier}",dependencies=[Depends(authorized)])
    def profile(identifier:str):
        row=ctrl.store.profile(identifier)
        if row is None: raise HTTPException(404,"Not found")
        return row

    @app.get("/api/graph",dependencies=[Depends(authorized)])
    def graph(): return graph_data(ctrl.store.profiles())

    @app.get("/api/logs",dependencies=[Depends(authorized)])
    def logs(limit:int=500): return ctrl.store.logs(limit)

    @app.post("/api/control",dependencies=[Depends(authorized)])
    async def control(request:Request):
        data=await request.json()
        cmd=data.get("cmd")
        try:
            if cmd=="start":
                return await ctrl.start(data.get("mode","osint"),data.get("target_id"),data.get("fps"))
            if cmd=="pause": await ctrl.pause()
            elif cmd=="resume": await ctrl.resume()
            elif cmd=="stop": await ctrl.stop()
            else: raise ValueError("Unknown command")
        except (RuntimeError,ValueError) as exc:
            raise HTTPException(409,str(exc))
        return ctrl.snapshot()

    @app.get("/api/config",dependencies=[Depends(authorized)])
    def config():
        return {"env":public_values(),"prompts":{name:get_prompt(name) for name in PROMPTS}}

    @app.post("/api/config",dependencies=[Depends(authorized)])
    async def config_save(request:Request):
        body=await request.json()
        try:
            if "env" in body: update(body["env"])
            for name,value in body.get("prompts",{}).items(): update_prompt(name,value)
            ctrl.reload()
            return {"ok":True}
        except (ValueError,RuntimeError,TypeError) as exc:
            raise HTTPException(400,str(exc))

    @app.websocket("/ws")
    async def websocket(ws:WebSocket):
        if ctrl.settings.token and ws.query_params.get("token")!=ctrl.settings.token:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            async with ctrl.bus.subscribe() as queue:
                await ws.send_json({"event":"status","data":ctrl.snapshot()})
                while True:
                    item=await queue.get()
                    await ws.send_json(item)
        except WebSocketDisconnect:
            pass

    @app.get("/")
    def index(): return FileResponse(web/"index.html")

    app.mount("/web",StaticFiles(directory=web),name="web")
    return app
