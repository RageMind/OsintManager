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
