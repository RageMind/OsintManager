"""Async task control shared by CLI and web interface."""
import asyncio
import time
from .config import Settings
from .store import Store
from .events import EventBus
from .planner import LLM

class Controller:
    def __init__(self):
        self.settings=Settings.load()
        self.store=Store(self.settings.database)
        self.bus=EventBus()
        self.llm=LLM(self.settings)
        self.task=None
        self.state="idle"
        self.mode="osint"
        self.current_target=""
        self.progress=0.0
        self.started=time.monotonic()
        self.stop_event=asyncio.Event()
        self.resume_event=asyncio.Event()
        self.resume_event.set()
        self.game_state={}
        self.last_decision={}

    def snapshot(self):
        return {"state":self.state,"mode":self.mode,"current_target":self.current_target,
                "progress":self.progress,"uptime":int(time.monotonic()-self.started),
                "game_state":self.game_state,"last_decision":self.last_decision,
                **self.store.counts()}

    def publish(self):
        self.bus.emit("status",self.snapshot())

    def log(self,level,message):
        item=self.store.log(level,message)
        path=self.settings.database.parent/"agent.log"
        with path.open("a",encoding="utf-8") as stream:
            stream.write(item["ts"]+" ["+level+"] "+str(message).replace("\\n"," ")+"\\n")
        self.bus.emit("log",item)
        print("["+level+"] "+str(message),flush=True)

    async def wait_running(self):
        await self.resume_event.wait()
        if self.stop_event.is_set():
            raise asyncio.CancelledError()

    def reload(self):
        if self.task and not self.task.done():
            raise RuntimeError("Stop active worker before changing configuration")
        self.settings=Settings.load()
        self.llm=LLM(self.settings)

    async def start(self,mode="osint",target_id=None,fps=None):
        if self.task and not self.task.done():
            raise RuntimeError("Worker is already active")
        if mode not in ("osint","game"):
            raise ValueError("Unknown mode")
        self.mode=mode
        self.stop_event=asyncio.Event()
        self.resume_event.set()
        self.state="running"
        self.progress=0.0
        self.publish()
        self.task=asyncio.create_task(self.worker(mode,target_id,fps))
        return self.snapshot()

    async def worker(self,mode,target_id,fps):
        try:
            if mode=="game":
                from .game_bot import run_game
                await run_game(self,fps or self.settings.fps)
            else:
                from .osint import run_osint
                await run_osint(self,target_id)
            self.state="idle"
        except asyncio.CancelledError:
            self.state="idle"
        except Exception as error:
            self.state="error"
            self.log("ERROR",str(error))
            self.bus.emit("error",{"where":mode,"msg":str(error)})
        finally:
            self.current_target=""
            self.progress=0.0
            self.publish()

    async def pause(self):
        if self.state!="running": raise RuntimeError("Worker is not running")
        self.state="paused"
        self.resume_event.clear()
        self.publish()

    async def resume(self):
        if self.state!="paused": raise RuntimeError("Worker is not paused")
        self.state="running"
        self.resume_event.set()
        self.publish()

    async def stop(self):
        self.stop_event.set()
        self.resume_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
        self.state="idle"
        self.publish()
