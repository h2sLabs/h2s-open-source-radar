import math, os, re, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
import requests
from AppKit import NSWorkspace
from db import add_activity, recent_activity, upsert_repo, load_settings, cleanup_activity, connect

API="https://api.github.com/search/repositories"
UA="H2S-Open-Source-Radar/1.0"
APP_KEYWORDS={
 "Logic Pro":"logic pro daw midi audio unit apple loops music production automation",
 "REAPER":"reaper daw midi vst audio automation scripting",
 "ACE Studio":"singing voice synthesis vocal midi lyric alignment ai music",
 "Synthesizer V":"singing voice synthesis vocal midi phoneme lyric alignment",
 "H2S Studio":"ai music generation composition arrangement stem midi vocal",
 "H2S Production Assistant":"singing voice synthesis vocal midi lyric alignment daw automation",
 "NeuralNote":"audio to midi music transcription pitch tracking polyphonic transcription",
 "MuScriptor":"audio to midi music transcription score midi",
 "OpenUtau":"singing voice synthesis vocal phoneme lyric midi",
 "GarageBand":"daw midi audio music production",
 "Ableton Live":"daw midi audio vst music production automation",
 "Cubase":"daw midi audio vst music production automation",
 "FL Studio":"daw midi audio vst music production automation",
 "Studio One":"daw midi audio vst music production automation",
 "Xcode":"macos swift audio unit plugin developer automation",
 "Cursor":"coding agent mcp developer automation",
 "Visual Studio Code":"coding agent mcp developer automation",
 "Terminal":"cli automation agent mcp developer tools",
 "iTerm2":"cli automation agent mcp developer tools",
 "Blender":"3d generation geometry vision reconstruction",
 "ComfyUI":"image video generation diffusion workflow",
}
CATEGORY_RULES=[
 ("작곡·음악 생성",["music generation","text to music","musicgen","song generation","composition","composer","music ai"]),
 ("DAW 자동화",["daw","logic pro","reaper","audio unit","vst","mcp","daw automation","apple loops"]),
 ("Audio→MIDI·채보",["audio to midi","transcription","midi transcription","music transcription","pitch tracking","note transcription"]),
 ("Stem·오디오 분리",["source separation","stem","demucs","separation","music separation"]),
 ("보컬·가창 합성",["singing voice","vocal synthesis","voice synthesis","phoneme","lyrics alignment","singing synthesis"]),
 ("Agent·MCP",["mcp","agent","computer use","automation","tool use","agentic"]),
 ("로컬 LLM",["mlx","local llm","llama.cpp","inference","ollama"]),
 ("영상·이미지 AI",["video generation","image generation","diffusion","comfyui","text to video"]),
 ("3D·비전",["3d","vision","reconstruction","slam","gaussian splatting","nerf"]),
]

def frontmost_app():
 try:
  a=NSWorkspace.sharedWorkspace().frontmostApplication()
  return (a.localizedName() or "",a.bundleIdentifier() or "")
 except Exception:return ("","")

def sample_activity():
 ws=NSWorkspace.sharedWorkspace()
 front_name,front_bundle=frontmost_app()
 active=[]
 try:
  for a in ws.runningApplications():
   name=a.localizedName() or ""
   if name in APP_KEYWORDS:
    bundle=a.bundleIdentifier() or ""
    add_activity(name,bundle,APP_KEYWORDS[name],"app")
    if name not in active: active.append(name)
 except Exception:
  pass
 if not active and front_name:
  add_activity(front_name,front_bundle,APP_KEYWORDS.get(front_name,""),"app")
 cleanup_activity()
 return " · ".join(active[:6]) if active else front_name

def scan_recent_project_signals(minutes=15):
 roots=[Path.home()/"Music",Path.home()/"Developer",Path.home()/"Documents",Path.home()/"AIProject"]
 try:
  roots.extend(Path("/Volumes").glob("*/AIProject"))
 except Exception:
  pass
 # Keep only existing, unique roots. No user-specific absolute paths are required.
 roots=list(dict.fromkeys(p for p in roots if p.exists()))
 seen=[]
 for root in roots:
  if not root.exists():continue
  try:
   p=subprocess.run(["find",str(root),"-maxdepth","3","-type","f","-mmin",f"-{minutes}"],
                    capture_output=True,text=True,timeout=8)
   for line in p.stdout.splitlines()[:80]:
    if any(x in line for x in ["/.git/","/node_modules/","/__pycache__/","/build/","/dist/"]):continue
    q=Path(line)
    signal=f"{q.parent.name} {q.name} {q.suffix}".strip()
    if signal not in seen:
     seen.append(signal); add_activity("", "", signal, "file")
  except Exception:pass
 return seen

def context_text(hours=72):
 rows=recent_activity(hours=hours,limit=500)
 parts=[]
 for r in rows:
  parts.extend([r.get("app_name",""),r.get("signal","")])
 return " ".join(parts).lower()

STOPWORDS={"ai","automation","agent","agents","audio","model","models","tool","tools","open","source",
 "app","studio","pro","generation","local","python","framework","system","use","using","based","with","for"}

def tokenize(text):
 return {t for t in re.findall(r"[a-z0-9+#.-]{2,}",(text or "").lower()) if t not in STOPWORDS}

def category_for(text):
 low=(text or "").lower()
 if any(x in low for x in ["music generation","text to music","song generation","musicgen","yue2","yue "]): return "작곡·음악 생성"
 if any(x in low for x in ["audio to midi","midi transcription","music transcription","automatic music transcription"]): return "Audio→MIDI·채보"
 if any(x in low for x in ["source separation","stem separation","demucs"]): return "Stem·오디오 분리"
 if any(x in low for x in ["singing voice","singing synthesis","vocal synthesis","lyric alignment"]): return "보컬·가창 합성"
 if any(x in low for x in ["logic pro","reaper","daw automation","audio unit","apple loops"]): return "DAW 자동화"
 best=("기타 AI",0)
 for cat,terms in CATEGORY_RULES:
  n=sum(1 for t in terms if t in low)
  if n>best[1]:best=(cat,n)
 return best[0]

def parse_dt(s):
 try:return datetime.fromisoformat((s or "").replace("Z","+00:00"))
 except Exception:return datetime(2000,1,1,tzinfo=timezone.utc)

def score_repo(item,settings,ctx):
 desc=item.get("description") or ""
 topics=" ".join(item.get("topics") or [])
 text=f"{item.get('name','')} {desc} {topics}".lower()
 stars=int(item.get("stargazers_count") or 0)
 star_score=min(38,int(math.log10(stars+1)*10))
 pushed=parse_dt(item.get("pushed_at")); created=parse_dt(item.get("created_at"))
 now=datetime.now(timezone.utc)
 pdays=max(0,(now-pushed).days); cdays=max(0,(now-created).days)
 recency=20 if pdays<=14 else 16 if pdays<=45 else 11 if pdays<=120 else 6 if pdays<=365 else 1
 fresh=10 if cdays<=90 else 7 if cdays<=180 else 3 if cdays<=365 else 0

 interest_tokens=set()
 for i in settings.get("interests",[]): interest_tokens |= tokenize(i)
 repo_tokens=tokenize(text)
 hits=repo_tokens & interest_tokens
 interest_score=min(24,len(hits)*4)

 ctx_tokens=tokenize(ctx)
 ctx_hits=repo_tokens & ctx_tokens
 context_score=min(24,len(ctx_hits)*4)

 score=min(100,star_score+recency+fresh+interest_score+context_score)
 why=[]
 if context_score>=12: why.append("현재 작업과 강하게 연관")
 elif context_score>0: why.append("최근 작업 맥락과 연관")
 if interest_score>=12: why.append("관심분야 일치")
 if stars>=10000: why.append(f"인기 {stars:,}★")
 elif stars>=1000: why.append(f"{stars:,}★")
 if pdays<=30: why.append("최근 활발히 업데이트")
 if cdays<=180: why.append("신규 프로젝트")
 return score,interest_score,context_score," · ".join(why[:4])

def search_queries(settings,ctx):
 min_stars=max(0,int(settings.get("min_stars",20)))
 general=[
  f'AI agent MCP stars:>{max(100,min_stars)}',
  f'"local LLM" inference stars:>{max(100,min_stars)}',
  f'"video generation" AI stars:>{max(100,min_stars)}',
  f'"3D reconstruction" AI stars:>{max(100,min_stars)}',
  f'AI created:>2026-01-01 stars:>{max(200,min_stars)}',
 ]
 interests=[str(x).strip() for x in settings.get("interests",[]) if str(x).strip()]
 deep=[]
 for i in range(0,min(len(interests),12),3):
  chunk=interests[i:i+3]
  terms=" OR ".join(f'"{x}"' if " " in x else x for x in chunk)
  deep.append(f'({terms}) stars:>{min_stars}')
 qs=deep[:4]+general
 low=ctx.lower()
 if "logic pro" in low: qs.append(f'"Logic Pro" automation MIDI stars:>{min_stars}')
 elif "reaper" in low: qs.append(f'REAPER automation MIDI stars:>{min_stars}')
 elif "ace studio" in low or "synthesizer v" in low: qs.append(f'"singing voice" "lyric alignment" stars:>{min_stars}')
 return qs[:10]

def rescore_cached():
 settings=load_settings(); ctx=context_text()
 with connect() as c:
  rows=c.execute("SELECT id,name,description,topics,stars,created_at,updated_at,pushed_at FROM repos WHERE hidden=0").fetchall()
  for r in rows:
   try:
    import json
    topics=json.loads(r["topics"] or "[]")
   except Exception:
    topics=[]
   item={"name":r["name"],"description":r["description"] or "","topics":topics,
         "stargazers_count":int(r["stars"] or 0),"created_at":r["created_at"] or "",
         "updated_at":r["updated_at"] or "","pushed_at":r["pushed_at"] or ""}
   score,interest_score,context_score,why=score_repo(item,settings,ctx)
   c.execute("UPDATE repos SET score=?,interest_score=?,context_score=?,why=? WHERE id=?",
             (score,interest_score,context_score,why,r["id"]))

class DiscoveryEngine:
 def __init__(self,progress=None):
  self.progress=progress or (lambda a,b,c:None)

 def run(self):
  settings=load_settings(); ctx=context_text()
  queries=search_queries(settings,ctx); headers={"Accept":"application/vnd.github+json","User-Agent":UA}
  token=os.environ.get("GITHUB_TOKEN","").strip()
  if token:headers["Authorization"]=f"Bearer {token}"
  seen={}; errors=[]
  for n,q in enumerate(queries,1):
   self.progress(n,len(queries),q)
   try:
    r=requests.get(API,params={"q":q,"sort":"stars","order":"desc","per_page":30},headers=headers,timeout=20)
    if r.status_code==403:
     errors.append("GitHub API rate limit"); break
    r.raise_for_status()
    for item in r.json().get("items",[]):
     seen[item["full_name"]]=item
   except Exception as e: errors.append(str(e))
  new=updated=0; top_new=[]
  for item in seen.values():
   score,interest_score,context_score,why=score_repo(item,settings,ctx)
   blob=" ".join([item.get("name",""),item.get("description") or ""," ".join(item.get("topics") or [])])
   repo={
    "full_name":item["full_name"],"name":item["name"],"owner":item.get("owner",{}).get("login",""),
    "html_url":item["html_url"],"description":item.get("description") or "","category":category_for(blob),
    "language":item.get("language") or "","license":(item.get("license") or {}).get("spdx_id") or "",
    "stars":item.get("stargazers_count",0),"forks":item.get("forks_count",0),"topics":item.get("topics") or [],
    "created_at":item.get("created_at",""),"updated_at":item.get("updated_at",""),"pushed_at":item.get("pushed_at",""),
    "score":score,"interest_score":interest_score,"context_score":context_score,"why":why}
   rid,created,changed=upsert_repo(repo)
   if created:
    new+=1
    if score>=int(settings.get("notify_score",82)): top_new.append(repo)
   elif changed: updated+=1
  top_new.sort(key=lambda x:x["score"],reverse=True)
  return {"found":len(seen),"new":new,"updated":updated,"errors":errors,"top_new":top_new[:5],"queries":queries}
