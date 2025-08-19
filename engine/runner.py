import os, time, json, sqlite3
from pathlib import Path
from dotenv import load_dotenv
from .gbt import fetch_template, make_job, write_job
from .submitter import submit_if_candidate

load_dotenv("config/.env")
DB_PATH=os.getenv("DB_PATH","./pool.db")
RUNTIME_JOB_JSON=os.getenv("RUNTIME_JOB_JSON","./runtime/current_job.json")

def db():
    con=sqlite3.connect(DB_PATH); con.execute("PRAGMA journal_mode=WAL;"); return con

def open_round(prevhash, difficulty, height):
    con=db(); cur=con.cursor()
    ts=int(time.time())
    cur.execute("INSERT INTO rounds(start_ts,prevhash,network_difficulty,status) VALUES(?,?,?,?)",
                (ts, prevhash, difficulty, "open"))
    con.commit(); con.close()

def main():
    Path("runtime").mkdir(parents=True,exist_ok=True)
    last_prev=None
    while True:
        try:
            t=fetch_template()
            prev=t["previousblockhash"]
            if prev!=last_prev:
                open_round(prev, t.get("difficulty",1.0), t["height"])
                last_prev=prev
            # refresh job (ntime/coinbase)
            j=make_job(t); write_job(j, RUNTIME_JOB_JSON)
            submit_if_candidate()  # assemble+submit if a candidate exists
            time.sleep(2)
        except Exception as e:
            print("Engine error:", e); time.sleep(3)

if __name__=="__main__": main()
