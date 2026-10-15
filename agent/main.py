"""CLI entry point."""
import argparse
import asyncio
import uvicorn
from .controller import Controller

def main():
    parser=argparse.ArgumentParser(description="Local OSINT and game console")
    parser.add_argument("--ui",action="store_true")
    parser.add_argument("--mode",choices=("osint","game"),default="osint")
    parser.add_argument("--targets",default="")
    parser.add_argument("--fps",type=float)
    args=parser.parse_args()
    app=Controller()
    if args.targets:
        with open(args.targets,encoding="utf-8-sig") as stream:
            for line in stream:
                target=line.strip()
                if target and not target.startswith("#"):
                    app.store.add_target(target)
    if args.ui:
        from .api import create_app
        uvicorn.run(create_app(app),host=app.settings.host,port=app.settings.port)
    else:
        async def work():
            await app.start(args.mode,fps=args.fps)
            await app.task
        try:
            asyncio.run(work())
        except KeyboardInterrupt:
            print("Interrupted")

if __name__=="__main__":
    main()
