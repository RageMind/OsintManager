"""Playwright/HTTP executor with cached robots policy and per-host pacing."""
import asyncio
import ipaddress
import random
import socket
import threading
import time
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit,urljoin
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser
from playwright.async_api import async_playwright

USER_AGENT="OsintManager/0.1 (authorized research)"
ROBOTS_CACHE={}
NEXT_REQUEST={}
POLICY_LOCK=threading.Lock()

class RobotsDenied(PermissionError):
    """A source forbids automated access for the configured user agent."""

def reset_policy():
    with POLICY_LOCK:
        ROBOTS_CACHE.clear()
        NEXT_REQUEST.clear()

def host_allowed(host,allowed):
    return any(host==item or host.endswith("."+item) for item in allowed)

async def check_url(url,settings):
    parts=urlsplit(url)
    host=(parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http","https") or not host or parts.username or parts.password:
        raise ValueError("Unsupported URL")
    if not host_allowed(host,settings.hosts):
        raise ValueError("Host not on OSINT_ALLOWED_HOSTS: "+host)
    try:
        addrs=await asyncio.to_thread(socket.getaddrinfo,host,parts.port or (443 if parts.scheme=="https" else 80))
        for item in addrs:
            ip=ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                raise ValueError("Non-public host address")
    except socket.gaierror as exc:
        raise ValueError("Host could not be resolved") from exc
    return url

async def rate_limit(host,settings):
    rate=settings.domain_rps
    if not 0<rate<=20: raise ValueError("Invalid OSINT_DOMAIN_RPS")
    with POLICY_LOCK:
        now=time.monotonic()
        slot=max(now,NEXT_REQUEST.get(host,now))
        NEXT_REQUEST[host]=slot+1/rate
    if slot>now: await asyncio.sleep(slot-now)

def retry_after(value):
    if not value: return 0.0
    try: return max(0.0,min(120.0,float(value)))
    except (ValueError,TypeError):
        try:
            dt=parsedate_to_datetime(value)
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            return max(0.0,min(120.0,(dt-datetime.now(timezone.utc)).total_seconds()))
        except (ValueError,TypeError,OverflowError): return 0.0

async def request_with_retry(client,url,settings):
    host=urlsplit(url).hostname.lower()
    for attempt in range(settings.retries+1):
        await rate_limit(host,settings)
        try:
            response=await client.get(url)
        except (httpx.TimeoutException,httpx.TransportError):
            if attempt>=settings.retries: raise
            await asyncio.sleep(min(30,2**attempt))
            continue
        if response.status_code in (429,500,502,503,504):
            if attempt>=settings.retries: response.raise_for_status()
            await asyncio.sleep(max(retry_after(response.headers.get("Retry-After")),
                                    min(30,2**attempt)))
            continue
        return response
    raise RuntimeError("HTTP retries exhausted")

async def robots_for(url,settings,client):
    parsed=urlsplit(url)
    origin=parsed.scheme+"://"+parsed.netloc.lower()
    if origin in ROBOTS_CACHE: return ROBOTS_CACHE[origin]
    robots_url=origin+"/robots.txt"
    await check_url(robots_url,settings)
    policy=RobotFileParser()
    policy.set_url(robots_url)
    try:
        response=await request_with_retry(client,robots_url,settings)
        if response.status_code==404:
            policy.allow_all=True
        elif response.status_code in (401,403):
            policy.disallow_all=True
        elif response.status_code==200:
            policy.parse(response.text[:500000].splitlines())
        else:
            policy.disallow_all=True
    except (httpx.HTTPError,ValueError,OSError):
        policy.disallow_all=True
    ROBOTS_CACHE[origin]=policy
    return policy

async def authorize(url,settings,client):
    await check_url(url,settings)
    policy=await robots_for(url,settings,client)
    if not policy.can_fetch(USER_AGENT,url):
        raise RobotsDenied("robots.txt disallows "+url)

def visible_html(html,limit):
    doc=HTMLParser(html)
    for node in doc.css("script,style,noscript,svg,template"):
        node.decompose()
    title=doc.css_first("title")
    body=doc.css_first("body")
    text=body.text(separator=" ",strip=True) if body else doc.text(separator=" ",strip=True)
    return {"title":title.text(strip=True) if title else "", "text":text[:limit]}

async def http_fallback(url,settings):
    async with httpx.AsyncClient(timeout=settings.timeout,follow_redirects=False,
                                  headers={"User-Agent":USER_AGENT}) as client:
        for _ in range(6):
            await authorize(url,settings,client)
            response=await request_with_retry(client,url,settings)
            if response.status_code in (301,302,303,307,308):
                location=response.headers.get("location")
                if not location: raise ValueError("Redirect without Location")
                url=urljoin(url,location)
                continue
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type","").lower():
                raise ValueError("Only HTML documents supported")
            info=visible_html(response.text[:2000000],settings.max_chars)
            return {"url":url,**info}
    raise ValueError("Too many redirects")

async def fetch_page(url,settings):
    async with httpx.AsyncClient(timeout=settings.timeout,follow_redirects=False,
                                  headers={"User-Agent":USER_AGENT}) as policy_client:
        await authorize(url,settings,policy_client)
        try:
            async with async_playwright() as playwright:
                browser=await playwright.chromium.launch(headless=True)
                try:
                    context=await browser.new_context(service_workers="block",
                                                       user_agent=USER_AGENT)
                    page=await context.new_page()
                    async def guarded(route):
                        try:
                            await authorize(route.request.url,settings,policy_client)
                            if route.request.resource_type in ("image","media","font"):
                                await route.abort()
                            else:
                                await rate_limit(urlsplit(route.request.url).hostname.lower(),settings)
                                await route.continue_()
                        except Exception:
                            await route.abort()
                    await page.route("**/*",guarded)
                    response=await page.goto(url,wait_until="domcontentloaded",
                                             timeout=settings.timeout*1000)
                    if response and response.status>=400:
                        raise ValueError("HTTP "+str(response.status))
                    result={"url":page.url,"title":await page.title(),
                            "text":(await page.locator("body").inner_text(timeout=5000))[:settings.max_chars]}
                    await authorize(result["url"],settings,policy_client)
                    return result
                finally:
                    await browser.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            return await http_fallback(url,settings)
