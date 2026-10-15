"""Offline robots, rate-limit, redirects and HTTP failure contract tests."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from agent import executor

def settings():
    return SimpleNamespace(domain_rps=10,timeout=1,retries=2,
                           max_chars=10000,hosts=frozenset({"example.org"}))

def session(monkeypatch,responder):
    original=httpx.AsyncClient
    transport=httpx.MockTransport(responder)
    monkeypatch.setattr(executor.httpx,"AsyncClient",
        lambda **kw:original(transport=transport,**kw))
    async def allow(url,settings):
        assert url.startswith("https://example.org/")
        return url
    monkeypatch.setattr(executor,"check_url",allow)
    executor.reset_policy()

def html():
    return httpx.Response(200,headers={"content-type":"text/html"},
                          text="<html><title>Valid</title><body>Allowed content</body></html>")

def test_robots_cached_and_disallowed(monkeypatch):
    requests=[]
    def handle(request):
        requests.append(request.url.path)
        if request.url.path=="/robots.txt":
            return httpx.Response(200,text="User-agent: *\nDisallow: /private\nAllow: /\n")
        return html()
    session(monkeypatch,handle)
    async def run():
        assert (await executor.http_fallback("https://example.org/open",settings()))["title"]=="Valid"
        assert (await executor.http_fallback("https://example.org/another",settings()))["title"]=="Valid"
        with pytest.raises(executor.RobotsDenied):
            await executor.http_fallback("https://example.org/private/record",settings())
    asyncio.run(run())
    assert requests.count("/robots.txt")==1
    assert "/private/record" not in requests

def test_429_retry_after(monkeypatch):
    hits=[]
    def handle(request):
        if request.url.path=="/robots.txt":
            return httpx.Response(404)
        hits.append(request.url.path)
        if len(hits)==1:
            return httpx.Response(429,headers={"Retry-After":"3"})
        return html()
    session(monkeypatch,handle)
    waits=[]
    original=asyncio.sleep
    async def fake_sleep(seconds):
        waits.append(seconds)
        await original(0)
    monkeypatch.setattr(executor.asyncio,"sleep",fake_sleep)
    result=asyncio.run(executor.http_fallback("https://example.org/page",settings()))
    assert result["title"]=="Valid"
    assert len(hits)==2
    assert any(n>=3 for n in waits)

def test_403_is_not_retried(monkeypatch):
    hits=[]
    def handle(request):
        if request.url.path=="/robots.txt": return httpx.Response(404)
        hits.append(request.url.path)
        return httpx.Response(403)
    session(monkeypatch,handle)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(executor.http_fallback("https://example.org/denied",settings()))
    assert hits==["/denied"]

def test_timeout_recovers(monkeypatch):
    hits=[]
    def handle(request):
        if request.url.path=="/robots.txt": return httpx.Response(404)
        hits.append(request.url.path)
        if len(hits)==1: raise httpx.ReadTimeout("simulated",request=request)
        return html()
    session(monkeypatch,handle)
    old_sleep=asyncio.sleep
    async def instant(_):
        await old_sleep(0)
    monkeypatch.setattr(executor.asyncio,"sleep",instant)
    assert asyncio.run(executor.http_fallback("https://example.org/page",settings()))["title"]=="Valid"
    assert len(hits)==2

def test_redirect_chain_rechecks_policy(monkeypatch):
    visited=[]
    def handle(request):
        visited.append(request.url.path)
        if request.url.path=="/robots.txt":
            return httpx.Response(200,text="User-agent: *\nAllow: /\nDisallow: /private")
        if request.url.path=="/one": return httpx.Response(302,headers={"Location":"/two"})
        if request.url.path=="/two": return httpx.Response(301,headers={"Location":"/three"})
        return html()
    session(monkeypatch,handle)
    result=asyncio.run(executor.http_fallback("https://example.org/one",settings()))
    assert result["url"]=="https://example.org/three"
    assert visited.count("/robots.txt")==1
    assert visited[-3:]==["/one","/two","/three"]

def test_redirect_to_forbidden_url_is_denied(monkeypatch):
    visited=[]
    def handle(request):
        visited.append(request.url.path)
        if request.url.path=="/robots.txt":
            return httpx.Response(200,text="User-agent: *\nDisallow: /private")
        if request.url.path=="/one": return httpx.Response(302,headers={"Location":"/private"})
        return html()
    session(monkeypatch,handle)
    with pytest.raises(executor.RobotsDenied):
        asyncio.run(executor.http_fallback("https://example.org/one",settings()))
    assert "/private" not in visited

def test_global_rate_limit_shared_by_requests(monkeypatch):
    executor.reset_policy()
    s=settings()
    s.domain_rps=2
    waits=[]
    old_sleep=asyncio.sleep
    async def capture(n):
        waits.append(n)
        await old_sleep(0)
    monkeypatch.setattr(executor.asyncio,"sleep",capture)
    async def run():
        await executor.rate_limit("example.org",s)
        await executor.rate_limit("example.org",s)
    asyncio.run(run())
    assert any(n>0.4 for n in waits)
    executor.reset_policy()
