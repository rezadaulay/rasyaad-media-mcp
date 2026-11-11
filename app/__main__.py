"""Small operational CLI: python -m app scan | status"""
import argparse, json
from app.database import initialize
from app.discovery import scan_library
from app.service import ingestion_status, list_videos

parser=argparse.ArgumentParser(prog="dakwah-engine")
parser.add_argument("command",choices=["scan","status","videos"])
args=parser.parse_args()
initialize()
if args.command=="scan": result=scan_library()
elif args.command=="status": result=ingestion_status()
else: result=list_videos(limit=200)
print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
