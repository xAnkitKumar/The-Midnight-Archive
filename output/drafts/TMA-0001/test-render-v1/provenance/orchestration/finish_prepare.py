from pathlib import Path
import sys,json,hashlib,shutil,math,re
import numpy as np
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.models import Script,Storyboard,NarrationMetadata,NarrationBeatTiming,WordTiming,AssetManifest,AssetManifestEntry
from midnight_archive.subtitles import WordCue,SubtitleCue,_wrap,validate_cues,write_srt,write_ass,SubtitleStyle,parse_srt
from midnight_archive.voiceover import read_wav,write_wav
from midnight_archive.procedural_audio import generate_score,_make_sfx,_resample,_fade
s=Settings.load(ROOT);db=Database(s.db_path);VID="TMA-0001"
out=ROOT/"output/drafts/TMA-0001/test-render-v1"
assert db.require_video(VID)["status"]=="STORYBOARD_READY"
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def save(path,data):
 with path.open("x",encoding="utf-8") as f:f.write(json.dumps(data,indent=2))
source=ROOT/"output/narration_review/TMA-0001-v3-bm_george/v4-rhythm"
audio=out/"audio/approved-narration-v4.wav";assert sha(audio)==sha(source/"narration-v4.wav")
full,rate,ch=read_wav(audio);duration=len(full)/rate
script_path=next((ROOT/"output/scripts").glob("TMA-0001-*-v3.json"));script=Script.model_validate_json(script_path.read_text(encoding="utf-8"))
board_path=next((ROOT/"output/storyboards").glob("TMA-0001-*-v3.json"));board=Storyboard.model_validate_json(board_path.read_text(encoding="utf-8"))
alignment=json.loads((out/"audio/alignment-v1.json").read_text(encoding="utf-8"))
words=[WordCue(**w) for w in alignment["words"]]
# Keep sentence/beat boundaries even for one-word reveal sentences.
groups=[]
for b in script.narration:
 ws=[w for w in words if w.beat==b.beat];sentence=[]
 for i,w in enumerate(ws):
  sentence.append(w)
  if re.search(r"[.!?]$",w.word) or i==len(ws)-1:
   count=math.ceil(len(sentence)/7)
   size,extra=divmod(len(sentence),count);offset=0
   for j in range(count):
    n=size+(j<extra);groups.append(sentence[offset:offset+n]);offset+=n
   sentence=[]
cues=[]
for i,g in enumerate(groups):
 start=max(0,g[0].start-.04)
 end=max(start+.65,g[-1].end+.14)
 if i+1<len(groups):end=min(end,groups[i+1][0].start-.07)
 assert end-start>=.25,(g,end-start)
 cues.append(SubtitleCue(i+1,round(start,3),round(end,3),_wrap(" ".join(w.word for w in g),32)))
assert not validate_cues(cues,words),validate_cues(cues,words)
srt=out/"audio/subtitles-v2.srt";ass=out/"audio/subtitles-v2.ass"
write_srt(cues,srt);write_ass(cues,ass,SubtitleStyle.from_settings(s))
assert " ".join(c.text.replace("\n"," ") for c in parse_srt(srt))==script.plain_text
txt=ass.read_text(encoding="utf-8-sig")
txt+=f"Dialogue: 1,0:00:00.00,0:00:55.20,Midnight,,0,0,0,,{{\\an8\\pos(540,78)\\fs26\\alpha&HCA&\\bord0\\shad0\\fsp4}}THE MIDNIGHT ARCHIVE\n"
ass.write_text(txt,encoding="utf-8-sig")
alignment["cues"]=[vars(c) for c in cues];alignment["subtitle_policy"]="Sentence and beat boundaries preserved, including one-word revelations."
save(out/"audio/alignment-v2.json",alignment)
old=NarrationMetadata.model_validate_json((source/"narration-metadata-v4.json").read_text(encoding="utf-8"))
beats=[]
for b in script.narration:
 ws=[w for w in words if w.beat==b.beat]
 beats.append(NarrationBeatTiming(beat=b.beat,text=b.text,start=ws[0].start,end=ws[-1].end,duration=round(ws[-1].end-ws[0].start,3)))
meta=old.model_copy(update={"alignment_method":alignment["method"],"words":[WordTiming(**vars(w)) for w in words],"beats":beats})
save(out/"audio/narration-metadata-v1.json",NarrationMetadata.model_validate(meta.model_dump()).model_dump(mode="json"))
first_beats=[1,4,5,6,7,8,9,10,11,12]
bounds=[0.0]+[round(max(0,next(w.start for w in words if w.beat==b)-.08),3) for b in first_beats[1:]]+[round(duration,3)]
new=board.model_dump()
for i,scene in enumerate(new["scenes"]):scene.update(start=bounds[i],end=bounds[i+1])
board2=Storyboard.model_validate(new);assert len(board2.scenes)==10
save(out/"storyboard-aligned-v1.json",board2.model_dump(mode="json"))
save(out/"provenance/import.json",{"approved_source":s.relative(source/"narration-v4.wav"),"source_sha256":sha(audio),"audio_copied_byte_identically":True,"duration":duration,"voice":"bm_george","speed":.96,"script_path":s.relative(script_path),"script_sha256":sha(script_path),"source_storyboard_path":s.relative(board_path),"source_storyboard_sha256":sha(board_path),"interpolation":alignment["interpolation"],"scene_bounds":bounds,"review_only":True})
imgroot=Path(r"C:\Users\LOQ\.codex\generated_images\01a1db72-c116-7460-bb69-7ccdb82753fe")
ids=["dd2ef358-cd28-45c4-a501-370b7f845c1a","8df85b9c-7c03-4d96-ad4e-09077f88b9ef","af4b7ffb-6bb4-4f26-8870-ac7f73c84028","b5c5af2e-c24f-4318-be18-6928bf4985eb","77c87637-246f-4413-b39a-808a7c78fc64","658b0147-b6b7-44e1-8289-3c2103e760ae","f216a933-29f6-4071-a56f-58ea0e66ebd0","0fc10635-94b1-4aac-8eb4-c40925e9069f","d58dd225-7ba9-47a5-8fc5-64597ce5bfab","a6f3587e-d288-4ee4-abfc-31c19c4c772a"]
assets=[]
for i,uid in enumerate(ids+["aba3446e-21ee-44e6-9d42-ee80775a4a2e"],1):
 src=imgroot/f"exec-{uid}.png";name=f"scene-{i:02d}-v1.png" if i<11 else "scene-01-angle-b-v1.png"
 dst=out/"visuals"/name;assert not dst.exists();shutil.copy2(src,dst)
 assets.append(AssetManifestEntry(asset_id=f"TMA-0001-preview1-image-{i:02d}",video_id=VID,kind="preview_image",path=s.relative(dst),provider="OpenAI built-in imagegen",source=str(src),license="AI-generated output; subject to applicable OpenAI service terms",commercial_use=True,attribution="Generated for The Midnight Archive; no external stock input; scene 4 identity reference.",sha256=sha(dst)))
shutil.copy2(ROOT/"work/test-render-v1/image-prompts.json",out/"provenance/image-prompts.json")
# Original synthesized score and SFX, with no third-party music or samples.
score_path=out/"audio/score-original-v1.wav";generate_score(score_path,duration,bpm=58,seed=3001)
score,sr,ch=read_wav(score_path)
assert sr==48000
n=len(score);t=np.arange(n)/sr
narr=_resample(full,rate,sr)
env=np.convolve(np.abs(narr)[::240],np.ones(25)/25,"same")
env=np.interp(np.arange(n)/240,np.arange(len(env)),env)
duck=1-.55*np.clip(env/.07,0,1)
music=score*(10**(-26/20))*duck[:,None]
# Stop the musical/piano bed at Mara's reveal; only restrained room drone remains.
reveal=bounds[7];music*=np.clip((reveal-t)/1.2,0,1)[:,None]
tailtone=(np.sin(2*np.pi*73.42*t)+.25*np.sin(2*np.pi*110*t))*.004
tailtone*=np.clip((t-(reveal-1))/1,0,1)*np.clip((duration-t)/.7,0,1)
music+=tailtone[:,None]
fx=np.zeros((n,2),dtype=np.float32);events=[]
def effect(name,at,length,peak_db,seed):
 data=_make_sfx(name,length,seed).astype(np.float32)
 data*=10**(peak_db/20)/max(float(np.max(np.abs(data))),1e-8)
 start=round(at*sr);end=min(n,start+len(data));fx[start:end]+=data[:end-start,None]
 events.append({"kind":name,"time":round(at,3),"duration":length,"peak_dbfs":peak_db})
effect("paper_rustle",.05,.65,-36,1)
effect("paper_crease",bounds[1]+.05,.4,-34,2)
effect("switch_click",bounds[2]+2.2,.3,-31,3)
effect("switch_click",bounds[3]+.15,.3,-32,4)
effect("rain",bounds[5],bounds[6]-bounds[5],-39,5)
effect("distant_siren",bounds[5]+1,3,-37,6)
effect("paper_crease",bounds[6]+.05,.5,-34,7)
effect("paper_crease",bounds[7]+.05,.4,-35,8)
effect("paper_rustle",bounds[8]+.05,.6,-33,9)
# Two original soft knock impulses in the corridor, no dramatic boom.
rng=np.random.default_rng(3001)
for at in [bounds[2]+.6,bounds[2]+.86]:
 tt=np.arange(int(.15*sr))/sr
 knock=(np.sin(2*np.pi*125*tt)*np.exp(-tt*50)+.12*rng.normal(size=len(tt))*np.exp(-tt*100))*.023
 start=round(at*sr);fx[start:start+len(knock)]+=knock[:,None]
 events.append({"kind":"original soft wood knock","time":round(at,3),"duration":.15,"peak_dbfs":float(20*np.log10(max(abs(knock))))})
mix=np.column_stack([narr,narr])+music+fx
assert np.max(np.abs(mix))<.95,"Mix headroom insufficient; no voice limiting allowed"
write_wav(out/"audio/music-bed-v1.wav",music,sr);write_wav(out/"audio/sfx-stem-v1.wav",fx,sr);write_wav(out/"audio/mix-v1.wav",mix,sr)
save(out/"audio/mix-plan-v1.json",{"voice_gain_db":0,"voice_source_byte_identical":True,"processing":"24 to 48kHz resample for mix only; no narration time or pitch change, no compression/limiter","music_gain_db":-26,"duck_max_db":round(20*np.log10(.45),2),"piano_stops_at":reveal,"events":events,"peak_dbfs":float(20*np.log10(np.max(np.abs(mix))))})
for name in ["score-original-v1.wav","music-bed-v1.wav","sfx-stem-v1.wav"]:
 p=out/"audio"/name
 assets.append(AssetManifestEntry(asset_id=f"TMA-0001-preview1-{p.stem}",video_id=VID,kind="preview_audio",path=s.relative(p),provider="local procedural synthesis",source="midnight_archive/procedural_audio.py plus isolated preview mix orchestration",license="Original production audio; no external recordings",commercial_use=True,sha256=sha(p)))
save(out/"provenance/asset-manifest-v1.json",AssetManifest(assets=assets).model_dump(mode="json"))
print("PREPARED",duration,"WORDS",len(words),"CUES",len(cues),"BOUNDS",bounds,"MIX PEAK",20*np.log10(np.max(np.abs(mix))),flush=True)
