from pathlib import Path
import sys,json,hashlib,shutil,re,difflib,os
os.environ["HF_HUB_OFFLINE"]="1"
import numpy as np
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.models import Script,Storyboard,NarrationMetadata,WordTiming,NarrationBeatTiming
from midnight_archive.voiceover import read_wav
from midnight_archive.subtitles import WhisperAligner,WordCue,display_tokens,align_beat_tokens,build_cues,validate_cues,write_srt,write_ass,SubtitleStyle,parse_srt
s=Settings.load(ROOT);db=Database(s.db_path);VID="TMA-0001"
assert db.require_video(VID)["status"]=="STORYBOARD_READY","Concurrent state change"
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
out=ROOT/"output/drafts/TMA-0001/test-render-v1"
out.mkdir(parents=True,exist_ok=False)
for d in ["audio","visuals","provenance"]: (out/d).mkdir()
protected={}
for folder in ["midnight_archive","config","tests","output/scripts","output/storyboards","output/narration_review","output/rendered","output/drafts/TMA-0001/audio"]:
 for p in (ROOT/folder).rglob("*"):
  if p.is_file() and "__pycache__" not in str(p):protected[p.relative_to(ROOT).as_posix()]=sha(p)
(out/"provenance/before-sha256.json").write_text(json.dumps(protected,indent=2),encoding="utf-8")
(out/"provenance/database-before.json").write_text(json.dumps({"video":dict(db.require_video(VID)),"artifacts":[dict(x) for x in db.list_artifacts(VID)]},indent=2),encoding="utf-8")
source=ROOT/"output/narration_review/TMA-0001-v3-bm_george/v4-rhythm"
audio=out/"audio/approved-narration-v4.wav";shutil.copy2(source/"narration-v4.wav",audio)
assert sha(audio)==sha(source/"narration-v4.wav")
full,rate,ch=read_wav(audio);duration=len(full)/rate
assert rate==24000 and ch==1 and abs(duration-55.19725)<1e-6
script_path=next((ROOT/"output/scripts").glob("TMA-0001-*-v3.json"));script=Script.model_validate_json(script_path.read_text(encoding="utf-8"))
board_path=next((ROOT/"output/storyboards").glob("TMA-0001-*-v3.json"));board=Storyboard.model_validate_json(board_path.read_text(encoding="utf-8"))
records=json.loads((source/"review-qc-v4.json").read_text(encoding="utf-8"))["generation_groups"]
def canonical(words):
 result=[];changes=[];i=0
 while i<len(words):
  found=False
  for count in (3,2,1):
   seq=words[i:i+count];joined="".join(re.sub("[^a-z0-9]","",w[0].lower()) for w in seq)
   if len(seq)==count and joined in {"threeohseven","threezeroseven","307","3oh7","3o7","twoforty","240"}:
    mapped="2:40" if joined in {"twoforty","240"} else "3:07"
    result.append((mapped,seq[0][1],seq[-1][2]));changes.append({"original":[w[0] for w in seq],"mapped":mapped});i+=count;found=True;break
  if not found: result.append(words[i]);i+=1
 return result,changes
aligner=WhisperAligner();words=[];rec=[];interpolations=[]
for r in records:
 start,end=r["start_sample"],r["end_sample"]
 detected=aligner._recognise(full[start:end],rate)
 assert detected
 mapped,changes=canonical(detected)
 tokens=display_tokens(r["display"])
 ws=align_beat_tokens(tokens,mapped,start/rate,(end-start)/rate)
 ids=[b.beat for b in script.narration[r["first_beat"]-1:r["last_beat"]] for _ in display_tokens(b.text)]
 assert len(ws)==len(ids)
 words.extend(WordCue(w.word,w.start,w.end,beat) for w,beat in zip(ws,ids))
 norm=lambda t:re.sub(r"[^\w'-]","",t.lower())
 sm=difflib.SequenceMatcher(a=[norm(t) for t in tokens],b=[norm(w[0]) for w in mapped],autojunk=False)
 exact={j for block in sm.get_matching_blocks() for j in range(block.a,block.a+block.size)}
 interpolations.append({"group":r["group"],"tokens":[t for j,t in enumerate(tokens) if j not in exact]})
 rec.append({"group":r["group"],"audio_start":start/rate,"audio_end":end/rate,"raw_words":detected,"canonical_time_mappings":changes})
 print("FRESH ALIGNMENT",r["group"]," ".join(w[0] for w in detected),flush=True)
assert " ".join(w.word for w in words)==script.plain_text
assert all(0<=w.start<w.end<=duration for w in words)
assert all(a.end<=b.start+.001 for a,b in zip(words,words[1:]))
cues=build_cues(words)
assert not validate_cues(cues,words)
write_srt(cues,out/"audio/subtitles-v1.srt")
write_ass(cues,out/"audio/subtitles-v1.ass",SubtitleStyle.from_settings(s))
assert " ".join(c.text.replace("\n"," ") for c in parse_srt(out/"audio/subtitles-v1.srt"))==script.plain_text
# Add branding independently of captions. 22% opacity, present from frame zero.
ass=out/"audio/subtitles-v1.ass";txt=ass.read_text(encoding="utf-8-sig")
txt+=f"Dialogue: 1,0:00:00.00,0:00:55.20,Midnight,,0,0,0,,{{\\an8\\pos(540,78)\\fs26\\alpha&HCA&\\bord0\\shad0\\fsp4}}THE MIDNIGHT ARCHIVE\n"
ass.write_text(txt,encoding="utf-8-sig")
method="fresh faster-whisper base.en int8 word timestamps from approved WAV in six connected passages; canonical time tokens; disclosed unmatched-token interpolation"
alignment={"method":method,"source_audio_sha256":sha(audio),"words":[vars(w) for w in words],"cues":[vars(c) for c in cues],"recognitions":rec,"interpolation":interpolations,"text_matches_script":True}
(out/"audio/alignment-v1.json").write_text(json.dumps(alignment,indent=2),encoding="utf-8")
old=NarrationMetadata.model_validate_json((source/"narration-metadata-v4.json").read_text(encoding="utf-8"))
beats=[]
for b in script.narration:
 ws=[w for w in words if w.beat==b.beat]
 beats.append(NarrationBeatTiming(beat=b.beat,text=b.text,start=ws[0].start,end=ws[-1].end))
meta=old.model_copy(update={"alignment_method":method,"words":[WordTiming(**vars(w)) for w in words],"beats":beats})
meta=NarrationMetadata.model_validate(meta.model_dump())
(out/"audio/narration-metadata-v1.json").write_text(meta.model_dump_json(indent=2),encoding="utf-8")
# Scene cuts land 80ms before each new scene's first word, retaining preceding suspense.
first_beats=[1,4,5,6,7,8,9,10,11,12]
bounds=[0.0]+[round(max(0,next(w.start for w in words if w.beat==b)-.08),3) for b in first_beats[1:]]+[round(duration,3)]
new=board.model_dump()
for i,scene in enumerate(new["scenes"]):scene.update(start=bounds[i],end=bounds[i+1])
board2=Storyboard.model_validate(new)
assert len(board2.scenes)==10 and all(a.end==b.start for a,b in zip(board2.scenes,board2.scenes[1:]))
(out/"storyboard-aligned-v1.json").write_text(board2.model_dump_json(indent=2),encoding="utf-8")
(out/"provenance/import.json").write_text(json.dumps({"approved_source":s.relative(source/"narration-v4.wav"),"source_sha256":sha(audio),"audio_copied_byte_identically":True,"duration":duration,"voice":"bm_george","speed":.96,"script_path":s.relative(script_path),"script_sha256":sha(script_path),"source_storyboard_path":s.relative(board_path),"source_storyboard_sha256":sha(board_path),"interpolation":interpolations,"scene_bounds":bounds,"review_only":True},indent=2),encoding="utf-8")
print("PREPARED",duration,"WORDS",len(words),"CUES",len(cues),"BOUNDS",bounds,"INTERPOLATION",interpolations,flush=True)
