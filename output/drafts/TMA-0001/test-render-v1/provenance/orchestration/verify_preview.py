from pathlib import Path
import sys,json,hashlib,subprocess,shutil
from PIL import Image,ImageDraw
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.renderer import VideoRenderer
from midnight_archive.errors import PipelineError
s=Settings.load(ROOT);db=Database(s.db_path)
out=ROOT/"output/drafts/TMA-0001/test-render-v1"
meta=json.loads((out/"render-metadata-v1.json").read_text())
qc=json.loads((out/"technical-qc-v1.json").read_text())
print(json.dumps({"probe":qc["probe"],"checks":[x for x in qc["checks"] if x["name"] in ["peak_level","mean_level","integrated_loudness","silent_sections","black_frames","subtitle_text","narration_not_cut"]]},indent=2))
video=ROOT/meta["mp4_path"];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=json.loads((out/"provenance/before-sha256.json").read_text())
changed=[p for p,h in before.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
assert not changed,changed
approved=out/"audio/approved-narration-v4.wav"
assert sha(approved)==sha(ROOT/"output/narration_review/TMA-0001-v3-bm_george/v4-rhythm/narration-v4.wav")
# Exercise renderer's existing-file refusal; it must stop before any encoding.
from midnight_archive.models import Storyboard
board=Storyboard.model_validate_json((out/"storyboard-aligned-v1.json").read_text(encoding="utf-8"))
try:
 VideoRenderer(s).render("TMA-0001",board,[out/f"visuals/scene-{i:02d}-v1.png" for i in range(1,11)],out/"audio/subtitles-v2.ass",out/"audio/mix-v1.wav",approved,video)
except PipelineError as e:
 assert "Refusing to overwrite" in str(e);print("OVERWRITE REFUSAL PASSED")
else:raise AssertionError("Overwrite guard failed")
assert sha(video)==qc["mp4_sha256"]
review=out/"review-frames";review.mkdir(exist_ok=False)
times=[0,.5,6,12,18,22,25,30,36.7,42,47.7,50.4,53,54.4]
for i,t in enumerate(times):
 dest=review/f"frame-{i:02d}-{t:05.2f}s.jpg"
 r=subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-ss",str(t),"-i",str(video),"-frames:v","1","-update","1",str(dest)],capture_output=True,text=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
 assert r.returncode==0,r.stderr
sheet=Image.new("RGB",(1400,780),"#171717");d=ImageDraw.Draw(sheet)
for i,t in enumerate(times):
 im=Image.open(review/f"frame-{i:02d}-{t:05.2f}s.jpg");im.thumbnail((190,350))
 x=(i%7)*200;y=(i//7)*390;sheet.paste(im,(x,y+25));d.text((x+4,y+4),f"{t:.2f}s",fill="white")
sheet.save(review/"encoded-contact-sheet.jpg")
# Additional true-peak measurement on final AAC decode.
r=subprocess.run(["ffmpeg","-hide_banner","-nostdin","-i",str(video),"-af","loudnorm=I=-18:TP=-1:LRA=11:print_format=json","-f","null","-"],capture_output=True,text=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
assert r.returncode==0,r.stderr
start=r.stderr.rfind("{");loud=json.loads(r.stderr[start:])
checks={"protected_files_verified":len(before),"protected_files_changed":changed,"approved_narration_sha256":sha(approved),"narration_import_byte_identical":True,"output_mp4_sha256":sha(video),"overwrite_refusal_passed":True,"existing_tests":80,"existing_test_exit_code":0,"current_status":db.require_video("TMA-0001")["status"],"final_audio_measurement":loud,"human_review_required":True}
(out/"verification-v1.json").open("x",encoding="utf-8").write(json.dumps(checks,indent=2))
shutil.copy2(ROOT/"work/test-render-v1/opening-angle-prompt.txt",out/"provenance/opening-angle-prompt.txt")
(out/"provenance/orchestration").mkdir()
for name in ["prepare.py","finish_prepare.py","run_preview.py"]:
 shutil.copy2(ROOT/"work/test-render-v1"/name,out/"provenance/orchestration"/name)
print("VERIFICATION",json.dumps(checks),flush=True)
