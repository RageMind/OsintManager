"""Async pub/sub for WebSockets."""
import asyncio
from contextlib import asynccontextmanager

class EventBus:
    def __init__(self):
        self.subscribers=set()
    def emit(self,event,data):
        for q in tuple(self.subscribers):
            if q.full():
                try: q.get_nowait()
                except asyncio.QueueEmpty: pass
            q.put_nowait({"event":event,"data":data})
    @asynccontextmanager
    async def subscribe(self):
        queue=asyncio.Queue(maxsize=200)
        self.subscribers.add(queue)
        try: yield queue
        finally: self.subscribers.discard(queue)
