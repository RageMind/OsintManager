"""Playwright browser executor with URL allowlist and private-network blocking."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urljoin

import httpx
from selectolax.parser import HTMLParser
from playwright.async_api import async_playwright

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
                                  headers={"User-Agent":"OsintManager/0.1 (authorized research)"}) as client:
        for _ in range(6):
            await check_url(url,settings)
            response=await client.get(url)
            if response.status_code in (301,302,303,307,308):
                url=urljoin(url,response.headers["location"])
                continue
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type","").lower():
                raise ValueError("Only HTML documents supported")
            info=visible_html(response.text[:2000000],settings.max_chars)
            return {"url":url,**info}
    raise ValueError("Too many redirects")

async def fetch_page(url,settings):
    await check_url(url,settings)
    browser_error=None
    try:
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=True)
            try:
                page=await browser.new_page()
                async def guarded(route):
                    try:
                        await check_url(route.request.url,settings)
                        if route.request.resource_type in ("image","media","font"):
                            await route.abort()
                        else:
                            await route.continue_()
                    except Exception:
                        await route.abort()
                await page.route("**/*",guarded)
                response=await page.goto(url,wait_until="domcontentloaded",
                                         timeout=settings.timeout*1000)
                if response and response.status>=400:
                    raise ValueError("HTTP "+str(response.status))
                data={"url":page.url,"title":await page.title(),
                      "text":(await page.locator("body").inner_text(timeout=5000))[:settings.max_chars]}
                await check_url(data["url"],settings)
                return data
            finally:
                await browser.close()
    except (Exception,):
        browser_error=True
    if browser_error:
        return await http_fallback(url,settings)
