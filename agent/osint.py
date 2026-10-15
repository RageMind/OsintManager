"""Supervised public-source processing loop."""
import asyncio
from .planner import plan
from .executor import fetch_page
from .extractor import extract
from .report import save_reports

async def run_osint(controller,target_id=None):
    store=controller.store
    rows=[store.target(target_id)] if target_id else store.targets()
    rows=[r for r in rows if r]
    if not rows:
        controller.log("WARN","No targets queued")
        return
    for index,target in enumerate(rows):
        await controller.wait_running()
        identifier=target["id"]
        controller.current_target=target["value"]
        controller.progress=index/len(rows)
        store.target_status(identifier,"running")
        controller.publish()
        controller.log("INFO","Processing "+target["value"])
        done=0
        last_error=""
        try:
            urls=await plan(controller.llm,target["value"],controller.settings.max_pages)
            for position,url in enumerate(urls):
                await controller.wait_running()
                try:
                    page=await fetch_page(url,controller.settings)
                    record=await extract(controller.llm,target["value"],page)
                    profile=store.upsert(identifier,record)
                    controller.bus.emit("profile",{"id":profile["id"],
                        "name":profile["names"][0] if profile["names"] else target["value"]})
                    controller.log("INFO","Fetched "+page["url"])
                    done+=1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error=str(exc)
                    controller.log("WARN","Skipped "+url+" - "+last_error)
                controller.progress=(index+(position+1)/max(1,len(urls)))/len(rows)
                controller.publish()
                await asyncio.sleep(controller.settings.delay)
        except asyncio.CancelledError:
            store.target_status(identifier,"pending")
            raise
        except Exception as exc:
            last_error=str(exc)
            controller.log("ERROR","Target failed: "+last_error)
        store.target_status(identifier,"done" if done else "error",
                            last_error if not done else "")
        controller.progress=(index+1)/len(rows)
        controller.publish()
    save_reports(store.profiles(),controller.settings.reports)
    controller.log("INFO","Exports complete")
