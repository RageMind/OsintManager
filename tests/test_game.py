"""Offline emergency hotkey and held-input regression tests."""
import asyncio
import sys
from types import SimpleNamespace

import pytest

from agent import game_bot

def test_release_all_only_tracked_keys(monkeypatch):
    released=[]
    fake=SimpleNamespace(keyUp=released.append)
    monkeypatch.setitem(sys.modules,"pyautogui",fake)
    game_bot.PRESSED.clear()
    game_bot.PRESSED.update({"w","space"})
    game_bot.release_all()
    assert set(released)=={"w","space"}
    assert not game_bot.PRESSED

@pytest.mark.parametrize("trigger",["esc","f10"])
def test_two_hotkeys_cancel_and_release(monkeypatch,trigger):
    callbacks={}
    removed=[]
    fake_keyboard=SimpleNamespace(
        add_hotkey=lambda key,callback: callbacks.setdefault(key,callback) and key,
        remove_hotkey=removed.append)
    monkeypatch.setitem(sys.modules,"keyboard",fake_keyboard)
    released=[]
    monkeypatch.setitem(sys.modules,"pyautogui",SimpleNamespace(keyUp=released.append))
    monkeypatch.setattr(game_bot,"snapshot",lambda monitor:("abc",(300,200)))
    game_bot.PRESSED.clear()

    class FakeLLM:
        async def ask(self,prompt,content):
            await asyncio.sleep(0)
            return {"action":"wait","params":{}}

    class FakeController:
        def __init__(self):
            self.settings=SimpleNamespace(game_memory=3)
            self.llm=FakeLLM()
            self.stop_event=asyncio.Event()
            self.resume_event=asyncio.Event()
            self.resume_event.set()
            self.bus=SimpleNamespace(emit=lambda *args:None)
            self.messages=[]
        async def wait_running(self):
            await self.resume_event.wait()
        def log(self,level,msg):
            self.messages.append((level,msg))

    async def run():
        ctrl=FakeController()
        task=asyncio.create_task(game_bot.run_game(ctrl,2))
        for _ in range(50):
            if len(callbacks)==2: break
            await asyncio.sleep(0.01)
        assert set(callbacks)=={"esc","f10"}
        game_bot.PRESSED.add("w")
        callbacks[trigger]()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ctrl.stop_event.is_set()
        assert not game_bot.PRESSED
        assert "w" in released
        assert set(removed)=={"esc","f10"}

    asyncio.run(run())


def test_self_check_reports_screen_size(monkeypatch,capsys):
    monkeypatch.setattr(game_bot,"snapshot",lambda monitor:("encoded",(1920,1080)))
    result=game_bot.self_check(True)
    assert result["hotkeys_registered"] is True
    assert result["screen_available"] is True
    assert result["screen_size"]==[1920,1080]
    assert result["os"]
    assert "GAME SELF-CHECK" in capsys.readouterr().out

def test_cleanup_after_key_release_raises_mid_action(monkeypatch):
    events=[]
    count={"up":0}
    def key_up(key):
        count["up"]+=1
        events.append(("up",key))
        if count["up"]==1: raise RuntimeError("keyboard temporarily busy")
    fake=SimpleNamespace(keyDown=lambda key:events.append(("down",key)),
                         keyUp=key_up,FAILSAFE=True)
    monkeypatch.setitem(sys.modules,"pyautogui",fake)
    game_bot.PRESSED.clear()
    with pytest.raises(RuntimeError):
        game_bot.do_action({"action":"press","params":{"key":"w"}},(100,100))
    assert "w" in game_bot.PRESSED
    game_bot.release_all()
    assert events==[("down","w"),("up","w"),("up","w")]
    assert not game_bot.PRESSED

def test_cleanup_attempts_every_held_key_even_if_one_fails(monkeypatch):
    events=[]
    def key_up(key):
        events.append(key)
        if key=="w": raise OSError("unavailable")
    monkeypatch.setitem(sys.modules,"pyautogui",SimpleNamespace(keyUp=key_up))
    game_bot.PRESSED.clear()
    game_bot.PRESSED.update({"w","space"})
    with pytest.raises(RuntimeError):
        game_bot.release_all()
    assert set(events)=={"w","space"}
    assert game_bot.PRESSED=={"w"}
    game_bot.PRESSED.clear()
