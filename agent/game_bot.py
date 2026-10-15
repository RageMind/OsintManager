"""Bounded game actions with threaded emergency hotkeys and key cleanup."""
import asyncio
import base64
import io
import json
import random
import threading
from collections import deque
from contextlib import suppress

from .config import get_prompt

PRESSED=set()
INPUT_LOCK=threading.RLock()
KEYS=("up","down","left","right","space","enter","tab","esc","w","a","s","d")

def snapshot(monitor):
    import mss
    from PIL import Image
    with mss.mss() as screen:
        grab=screen.grab(monitor or screen.monitors[1])
        picture=Image.frombytes("RGB",grab.size,grab.rgb)
        picture.thumbnail((1280,720))
        stream=io.BytesIO()
        picture.save(stream,format="JPEG",quality=75)
        return base64.b64encode(stream.getvalue()).decode("ascii"),grab.size

def do_action(decision,dimensions):
    import pyautogui
    action=decision.get("action","wait")
    params=decision.get("params",{})
    if not isinstance(params,dict): raise ValueError("Invalid action params")
    pyautogui.FAILSAFE=True
    with INPUT_LOCK:
        if action=="wait": return
        if action=="move":
            x=int(params.get("x",0)); y=int(params.get("y",0))
            if 0<=x<dimensions[0] and 0<=y<dimensions[1]:
                pyautogui.moveTo(x,y,duration=random.uniform(.05,.25))
        elif action=="click":
            button=params.get("button","left")
            if button not in ("left","right"): raise ValueError("Invalid button")
            pyautogui.click(button=button)
        elif action=="press":
            key=params.get("key","")
            if key not in KEYS: raise ValueError("Invalid key")
            PRESSED.add(key)
            try:
                pyautogui.keyDown(key)
            finally:
                try: pyautogui.keyUp(key)
                finally: PRESSED.discard(key)
        else:
            raise ValueError("Unsupported action")

def release_all():
    with INPUT_LOCK:
        if not PRESSED: return
        import pyautogui
        for key in tuple(PRESSED):
            try: pyautogui.keyUp(key)
            finally: PRESSED.discard(key)

def install_hotkeys(flag,logger):
    try:
        import keyboard
        handles=[keyboard.add_hotkey("esc",flag.set),
                 keyboard.add_hotkey("f10",flag.set)]
        return keyboard,handles
    except (ImportError,OSError,PermissionError) as error:
        logger("WARN","Global hotkeys unavailable: "+str(error))
        return None,[]

async def watch_hotkeys(flag,controller,task):
    while not flag.is_set():
        await asyncio.sleep(0.05)
    controller.stop_event.set()
    task.cancel()

async def run_game(controller,fps):
    history=deque(maxlen=controller.settings.game_memory)
    llm=controller.llm
    frame_delay=1/max(.2,min(5,fps))
    emergency=threading.Event()
    keyboard,handles=install_hotkeys(emergency,controller.log)
    watcher=asyncio.create_task(watch_hotkeys(emergency,controller,asyncio.current_task()))
    try:
        while not controller.stop_event.is_set():
            await controller.wait_running()
            encoded,dimensions=await asyncio.to_thread(snapshot,None)
            state=await llm.ask(get_prompt("game_state"),[{
                "type":"text","text":"Describe observable game state as JSON."},{
                "type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+encoded}}])
            decision=await llm.ask(get_prompt("game_decision"),
                json.dumps({"state":state,"history":list(history)},ensure_ascii=False))
            if decision.get("action") not in ("wait","move","click","press"):
                raise ValueError("Unsupported action")
            controller.last_decision=decision
            controller.game_state=state
            await asyncio.sleep(random.uniform(.05,.25))
            await asyncio.to_thread(do_action,decision,dimensions)
            history.append({"state":state,"decision":decision})
            controller.bus.emit("game_frame",{
                "image":"data:image/jpeg;base64,"+encoded,
                "action":decision["action"]})
            controller.log("INFO","Game action: "+json.dumps(decision,ensure_ascii=False))
            await asyncio.sleep(frame_delay)
    except asyncio.CancelledError:
        controller.log("WARN","Game stopped")
        raise
    except Exception as error:
        controller.log("ERROR","Game error: "+str(error))
        controller.bus.emit("error",{"where":"game","msg":str(error)})
        raise
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        if keyboard:
            for handle in handles:
                with suppress(Exception):
                    keyboard.remove_hotkey(handle)
        await asyncio.to_thread(release_all)
