"""Optional game loop. Input and display libraries are imported only in game mode."""
import asyncio
import base64
import io
import json
import random
from collections import deque

from .config import get_prompt

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
    if action=="wait": return
    if action=="move":
        x=int(params.get("x",0)); y=int(params.get("y",0))
        if 0<=x<dimensions[0] and 0<=y<dimensions[1]:
            pyautogui.moveTo(x,y,duration=random.uniform(.05,.25))
    elif action=="click":
        button=params.get("button","left")
        if button in ("left","right"):
            pyautogui.click(button=button)
    elif action=="press":
        key=params.get("key","")
        if key in ("up","down","left","right","space","enter","tab","esc","w","a","s","d"):
            pyautogui.press(key)
    else:
        raise ValueError("Unsupported action")

def esc_pressed():
    try:
        import keyboard
        return bool(keyboard.is_pressed("esc"))
    except (ImportError,OSError,PermissionError):
        return False

async def run_game(controller,fps):
    history=deque(maxlen=controller.settings.game_memory)
    llm=controller.llm
    frame_delay=1/max(.2,min(5,fps))
    while not controller.stop_event.is_set():
        await controller.wait_running()
        if esc_pressed():
            controller.log("WARN","Esc emergency stop")
            break
        try:
            encoded,dimensions=await asyncio.to_thread(snapshot,None)
            state=await llm.ask(get_prompt("game_state"),[{
                "type":"text","text":"Describe observable game state as JSON."},{
                "type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+encoded}}])
            decision=await llm.ask(get_prompt("game_decision"),
                json.dumps({"state":state,"history":list(history)},ensure_ascii=False))
            if decision.get("action") not in ("wait","move","click","press"):
                raise ValueError("Unsafe/unsupported game action")
            controller.last_decision=decision
            controller.game_state=state
            await asyncio.sleep(random.uniform(.05,.25))
            await asyncio.to_thread(do_action,decision,dimensions)
            history.append({"state":state,"decision":decision})
            controller.bus.emit("game_frame",{
                "image":"data:image/jpeg;base64,"+encoded,
                "action":decision["action"]})
            controller.log("INFO","Game action: "+json.dumps(decision,ensure_ascii=False))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            controller.log("ERROR","Game step: "+str(error))
            controller.bus.emit("error",{"where":"game","msg":str(error)})
            await asyncio.sleep(2)
        await asyncio.sleep(frame_delay)
