import json, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

APP_DIR=Path.home()/"Library"/"Application Support"/"H2S Open Source Radar"
DB_PATH=APP_DIR/"radar.sqlite3"; SETTINGS_PATH=APP_DIR/"settings.json"
DEFAULT_SETTINGS={
 "interests":["AI music generation","composition automation","arrangement","Logic Pro automation",
 "REAPER automation","MIDI","audio to MIDI","music transcription","stem separation",
 "singing voice synthesis","vocal synthesis","lyric alignment","DAW MCP","music agent"],
 "auto_refresh_hours":6,"context_monitoring":True,"notify_score":82,"recent_days":365,
 "min_stars":20,"start_at_login":True,"last_scan_epoch":0}

def now_iso(): return datetime.now(timezone.utc).isoformat()
def connect():
 APP_DIR.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
 with connect() as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS repos(
   id INTEGER PRIMARY KEY AUTOINCREMENT,full_name TEXT UNIQUE,name TEXT,owner TEXT,html_url TEXT,
   description TEXT,category TEXT,language TEXT,license TEXT,stars INTEGER,forks INTEGER,
   topics TEXT,created_at TEXT,updated_at TEXT,pushed_at TEXT,score INTEGER,interest_score INTEGER,
   context_score INTEGER,why TEXT,first_seen TEXT,last_seen TEXT,is_new INTEGER DEFAULT 1,
   favorite INTEGER DEFAULT 0,hidden INTEGER DEFAULT 0);
  CREATE INDEX IF NOT EXISTS idx_repo_score ON repos(score DESC);
  CREATE TABLE IF NOT EXISTS activity(
   id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,app_name TEXT,bundle_id TEXT,signal TEXT,signal_type TEXT);
  CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts DESC);
  """)

def load_settings():
 APP_DIR.mkdir(parents=True,exist_ok=True)
 try: data=json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
 except Exception: data={}
 out=dict(DEFAULT_SETTINGS); out.update(data)
 if not SETTINGS_PATH.exists(): save_settings(out)
 return out

def save_settings(data):
 out=dict(DEFAULT_SETTINGS); out.update(data); APP_DIR.mkdir(parents=True,exist_ok=True)
 SETTINGS_PATH.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8"); return out

def upsert_repo(x):
 ts=now_iso(); topics=json.dumps(x.get("topics") or [],ensure_ascii=False)
 with connect() as c:
  old=c.execute("SELECT id,stars,score FROM repos WHERE full_name=?",(x["full_name"],)).fetchone()
  vals=(x["name"],x.get("owner",""),x["html_url"],x.get("description",""),x.get("category",""),
        x.get("language",""),x.get("license",""),int(x.get("stars") or 0),int(x.get("forks") or 0),
        topics,x.get("created_at",""),x.get("updated_at",""),x.get("pushed_at",""),int(x.get("score") or 0),
        int(x.get("interest_score") or 0),int(x.get("context_score") or 0),x.get("why",""),ts)
  if old:
   changed=int(old["stars"] or 0)!=int(x.get("stars") or 0) or int(old["score"] or 0)!=int(x.get("score") or 0)
   c.execute("""UPDATE repos SET name=?,owner=?,html_url=?,description=?,category=?,language=?,license=?,
    stars=?,forks=?,topics=?,created_at=?,updated_at=?,pushed_at=?,score=?,interest_score=?,context_score=?,
    why=?,last_seen=?,is_new=CASE WHEN ? THEN 1 ELSE is_new END WHERE full_name=?""",vals+(1 if changed else 0,x["full_name"]))
   return old["id"],False,changed
  cur=c.execute("""INSERT INTO repos(name,owner,html_url,description,category,language,license,stars,forks,topics,
    created_at,updated_at,pushed_at,score,interest_score,context_score,why,last_seen,is_new,full_name,first_seen)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",vals+(1,x["full_name"],ts))
  return cur.lastrowid,True,False

def query_repos(category="",mode="all",search="",limit=500):
 clauses=["hidden=0"]; args=[]
 if category: clauses.append("category=?"); args.append(category)
 if mode=="new": clauses.append("is_new=1")
 elif mode=="favorite": clauses.append("favorite=1")
 elif mode=="context": clauses.append("context_score>=12")
 elif mode=="hot": clauses.append("score>=78")
 if search:
  q=f"%{search}%"; clauses.append("(full_name LIKE ? OR description LIKE ? OR topics LIKE ? OR why LIKE ?)")
  args.extend([q,q,q,q])
 args.append(limit)
 with connect() as c:
  rows=c.execute(f"SELECT * FROM repos WHERE {' AND '.join(clauses)} ORDER BY score DESC,stars DESC LIMIT ?",args).fetchall()
  out=[]
  for r in rows:
   d=dict(r)
   try:d["topics"]=json.loads(d.get("topics") or "[]")
   except Exception:d["topics"]=[]
   out.append(d)
  return out

def repo_by_id(i):
 with connect() as c:
  r=c.execute("SELECT * FROM repos WHERE id=?",(i,)).fetchone()
  if not r:return None
  d=dict(r)
  try:d["topics"]=json.loads(d.get("topics") or "[]")
  except Exception:d["topics"]=[]
  return d

def mark_read(i):
 with connect() as c:c.execute("UPDATE repos SET is_new=0 WHERE id=?",(i,))
def set_favorite(i,v):
 with connect() as c:c.execute("UPDATE repos SET favorite=? WHERE id=?",(1 if v else 0,i))
def set_hidden(i,v=True):
 with connect() as c:c.execute("UPDATE repos SET hidden=? WHERE id=?",(1 if v else 0,i))

def add_activity(app_name="",bundle_id="",signal="",signal_type="app"):
 with connect() as c:c.execute("INSERT INTO activity(ts,app_name,bundle_id,signal,signal_type) VALUES(?,?,?,?,?)",
  (now_iso(),app_name,bundle_id,signal,signal_type))

def recent_activity(hours=72,limit=500):
 cutoff=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()
 with connect() as c:return [dict(r) for r in c.execute(
  "SELECT * FROM activity WHERE ts>=? ORDER BY ts DESC LIMIT ?",(cutoff,limit)).fetchall()]

def cleanup_activity(days=14):
 cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
 with connect() as c:c.execute("DELETE FROM activity WHERE ts<?",(cutoff,))

def stats():
 with connect() as c:
  r=c.execute("""SELECT COUNT(*) total,SUM(is_new=1) new_count,SUM(favorite=1) favorite_count,
   SUM(score>=78) hot_count,SUM(context_score>=12) context_count FROM repos WHERE hidden=0""").fetchone()
  return {k:int(r[k] or 0) for k in r.keys()}
