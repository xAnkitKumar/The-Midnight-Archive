from pathlib import Path
import sys,json,hashlib,subprocess,shutil
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from midnight_archive.config import Settings
from midnight_archive.database import Database
s=Settings.load(ROOT);db=Database(s.db_path)
out=ROOT/"output/drafts/TMA-0001/test-render-v1"
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
meta=json.loads((out/"render-metadata-v1.json").read_text());video=ROOT/meta["mp4_path"]
qc=json.loads((out/"technical-qc-v1.json").read_text())
before=json.loads((out/"provenance/before-sha256.json").read_text())
changed=[p for p,h in before.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
assert not changed
audio=out/"audio/approved-narration-v4.wav";source=ROOT/"output/narration_review/TMA-0001-v3-bm_george/v4-rhythm/narration-v4.wav"
assert sha(audio)==sha(source)
r=subprocess.run(["ffmpeg","-hide_banner","-nostdin","-i",str(video),"-af","loudnorm=I=-18:TP=-1:LRA=11:print_format=json","-f","null","-"],capture_output=True,text=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
assert r.returncode==0
loud,_=json.JSONDecoder().raw_decode(r.stderr[r.stderr.rfind("{"):])
checks={"protected_files_verified":len(before),"protected_files_changed":changed,"approved_narration_sha256":sha(audio),"narration_import_byte_identical":True,"output_mp4_sha256":sha(video),"overwrite_refusal_passed":True,"existing_tests":80,"existing_test_exit_code":0,"current_status":db.require_video("TMA-0001")["status"],"final_audio_measurement":loud,"human_review_required":True}
(out/"verification-v1.json").open("x",encoding="utf-8").write(json.dumps(checks,indent=2))
shutil.copy2(ROOT/"work/test-render-v1/opening-angle-prompt.txt",out/"provenance/opening-angle-prompt.txt")
(out/"provenance/orchestration").mkdir()
for name in ["prepare.py","finish_prepare.py","run_preview.py","verify_preview.py"]:
 shutil.copy2(ROOT/"work/test-render-v1"/name,out/"provenance/orchestration"/name)
print(json.dumps(checks,indent=2))
print("SCENES",json.dumps(meta["scene_timings"]))
