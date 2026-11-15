from pathlib import Path
import sys,json,hashlib,shutil,subprocess,copy
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.models import Script,Storyboard,NarrationMetadata,AssetManifest,RenderMetadata
from midnight_archive.renderer import VideoRenderer
from midnight_archive.technical_qc import run_technical_qc
from midnight_archive.subtitles import parse_srt
from PIL import Image,ImageDraw
VID="TMA-0001";s=Settings.load(ROOT);db=Database(s.db_path)
out=ROOT/"output/drafts/TMA-0001/test-render-v1"
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def save(path,data):
 with path.open("x",encoding="utf-8") as f:f.write(json.dumps(data,indent=2))
def inputs():
 provenance=json.loads((out/"provenance/import.json").read_text())
 assert sha(ROOT/provenance["approved_source"])==provenance["source_sha256"]
 assert sha(out/"audio/approved-narration-v4.wav")==provenance["source_sha256"]
 assert sha(ROOT/provenance["script_path"])==provenance["script_sha256"]
 assert sha(ROOT/provenance["source_storyboard_path"])==provenance["source_storyboard_sha256"]
 before=json.loads((out/"provenance/before-sha256.json").read_text())
 changed=[p for p,h in before.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
 assert not changed,changed
 script=Script.model_validate_json((ROOT/provenance["script_path"]).read_text(encoding="utf-8"))
 board=Storyboard.model_validate_json((out/"storyboard-aligned-v1.json").read_text(encoding="utf-8"))
 meta=NarrationMetadata.model_validate_json((out/"audio/narration-metadata-v1.json").read_text(encoding="utf-8"))
 manifest=AssetManifest.model_validate_json((out/"provenance/asset-manifest-v1.json").read_text(encoding="utf-8"))
 assert meta.voice=="bm_george" and meta.length_scale==.96 and abs(meta.duration-55.19725)<.001
 assert " ".join(c.text.replace("\n"," ") for c in parse_srt(out/"audio/subtitles-v2.srt"))==script.plain_text
 assert len(board.scenes)==10 and board.scenes[0].start==0
 for a in manifest.assets:assert sha(ROOT/a.path)==a.sha256,a.path
 for a,b in zip(board.scenes,board.scenes[1:]):assert a.end==b.start
 return script,board,meta,manifest
raw=copy.deepcopy(s.raw)
raw.setdefault("render",{}).update(zoom=.018,transition_seconds=.20,cut_seconds=.06)
local=Settings(s.root,raw,s.brand)
class PreviewRenderer(VideoRenderer):
 def _run(self,args,cwd,timeout=900):
  args=list(args)
  if "-filter_complex" in args:
   idx=args.index("-filter_complex")+1
   args[idx]=args[idx].replace("fade=t=in:st=0:d=0.35,","")
   args[idx]=args[idx].replace("fade=t=out:st=54.497:d=0.70","fade=t=out:st=54.597:d=0.60")
   args[idx]=args[idx].replace("afade=t=in:st=0:d=0.2,","").replace("afade=t=out:st=54.697:d=0.5,","")
   args[1:1]=["-filter_complex_threads","1"]
  # Bound decoder/encoder threading to avoid memory pressure from ten sources.
  pos=0
  while pos<len(args):
   if args[pos]=="-i":args[pos:pos]=["-threads","1"];pos+=4
   else:pos+=1
  if args[-1].lower().endswith(".mp4"):args[-1:-1]=["-threads","4"]
  return super()._run(args,cwd,timeout)
 def _xfade_graph(self,clips,timings):
  # Restrained dissolves; no generic vertical push/whip effects.
  parts=[];last="0:v";offset=0
  for i in range(1,len(clips)):
   prev=timings[i-1];offset+=prev.duration;label=f"x{i}"
   parts.append(f"[{last}][{i}:v]xfade=transition=fade:duration={prev.transition_out:.3f}:offset={offset:.3f}[{label}]");last=label
  return ";".join(parts),last
 def _render_scene_clip(self,image_path,clip_path,clip_duration,index,work):
  print("ENCODING SCENE",index,clip_duration,flush=True)
  if index!=1:return super()._render_scene_clip(image_path,clip_path,clip_duration,index,work)
  # A motivated reverse angle within logical scene 1 breaks the ten-second hold.
  first=round(5.12*self.fps)/self.fps
  a=clip_path.with_name("opening-a.mp4");b=clip_path.with_name("opening-b.mp4")
  super()._render_scene_clip(image_path,a,first,101,work)
  super()._render_scene_clip(out/"visuals/scene-01-angle-b-v1.png",b,clip_duration-first,102,work)
  lst=work/"scenes/opening-concat.txt";lst.write_text("file 'opening-a.mp4'\nfile 'opening-b.mp4'\n",encoding="utf-8")
  result=self._run([self.ffmpeg,"-hide_banner","-loglevel","error","-f","concat","-safe","0","-i",lst.name,"-c","copy",clip_path.name],work/"scenes")
  assert result.returncode==0,result.stderr
renderer=PreviewRenderer(local)
def proofs():
 script,board,meta,manifest=inputs()
 proof=ROOT/"work/test-render-v1/proofs";proof.mkdir(exist_ok=False)
 shutil.copy2(out/"audio/subtitles-v2.ass",proof/"subs.ass")
 (proof/"fonts").mkdir()
 shutil.copy2(ROOT/str(s.get("render.subtitle.font_file","assets/fonts/Montserrat-Bold.ttf")),proof/"fonts/Montserrat-Bold.ttf")
 samples=[(1,.5),(1,6),(2,12),(3,18),(4,22),(5,25),(6,30),(7,36.7),(8,42),(9,47.7),(10,53)]
 for j,(scene,time) in enumerate(samples):
  image=out/f"visuals/scene-{scene:02d}-v1.png"
  if scene==1 and time>5.12:image=out/"visuals/scene-01-angle-b-v1.png"
  target=proof/f"proof-{j:02d}.jpg"
  vf=f"scale=1080:1920,setsar=1,setpts=PTS+{time}/TB,ass=subs.ass:fontsdir=fonts"
  r=renderer._run([renderer.ffmpeg,"-hide_banner","-loglevel","error","-i",str(image),"-vf",vf,"-frames:v","1","-update","1",str(target)],proof,90)
  assert r.returncode==0,r.stderr
 sheet=Image.new("RGB",(1350,1000),"#151515");d=ImageDraw.Draw(sheet)
 for j,(scene,time) in enumerate(samples):
  im=Image.open(proof/f"proof-{j:02d}.jpg");im.thumbnail((215,450))
  x=(j%6)*225;y=(j//6)*500;sheet.paste(im,(x,y+24));d.text((x+4,y+3),f"Scene {scene} / {time:.1f}s",fill="white")
 sheet.save(proof/"contact-sheet.jpg")
 print("PROOFS",proof,flush=True)
def register(kind,path):
 db.add_artifact(VID,kind,db.next_artifact_version(VID,kind),s.relative(path),sha(path))
def render():
 script,board,meta,manifest=inputs()
 assert db.require_video(VID)["status"]=="STORYBOARD_READY","Preview import requires STORYBOARD_READY"
 # Refuse a second full test render in this authorization package.
 lock=out/"provenance/render-authorized-once.json";save(lock,{"scope":"One full test render only","human_approval":"User approved v4 and one test render","narration_sha256":sha(out/"audio/approved-narration-v4.wav")})
 v=db.next_artifact_version(VID,"storyboard")
 boardpath=ROOT/f"output/storyboards/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v{v}.json"
 save(boardpath,board.model_dump(mode="json"));register("storyboard",boardpath);db.set_storyboard(VID,board.model_dump(mode="json"))
 register("asset_manifest",out/"provenance/asset-manifest-v1.json")
 for a in manifest.assets:
  db.add_asset(VID,a.kind,a.path,a.sha256,provider=a.provider,license_name=a.license,source_url=a.source,commercial_use=a.commercial_use,attribution=a.attribution)
 db.transition(VID,"ASSETS_READY","codex-test-render","Versioned preview manifest; 10 scenes plus opening reverse angle.")
 for kind,p in [("narration","approved-narration-v4.wav"),("narration_metadata","narration-metadata-v1.json"),("subtitles","subtitles-v2.srt"),("subtitle_stylesheet","subtitles-v2.ass"),("word_alignment","alignment-v2.json"),("audio_mix","mix-v1.wav")]:
  register(kind,out/"audio"/p)
 db.transition(VID,"AUDIO_READY","codex-test-render","Approved v4 copied byte-identically; fresh alignment/subtitles and restrained original mix.")
 version=db.next_artifact_version(VID,"render")
 target=ROOT/f"output/rendered/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v{version}.mp4"
 tmp=ROOT/"work/test-render-v1/encode-work";assert not tmp.exists()
 result=renderer.render(VID,board,[out/f"visuals/scene-{i:02d}-v1.png" for i in range(1,11)],out/"audio/subtitles-v2.ass",out/"audio/mix-v1.wav",out/"audio/approved-narration-v4.wav",target,work_dir=tmp)
 metapath=out/"render-metadata-v1.json";save(metapath,result.metadata.model_dump(mode="json"))
 register("render_metadata",metapath);register("render",target)
 db.transition(VID,"RENDERED","codex-test-render","One authorized 1080x1920 human-review preview; not approved for release.")
 print("RENDER COMPLETE",target,flush=True)
 report=run_technical_qc(VID,target,out/"audio/subtitles-v2.srt",meta,script,result.metadata,s,expected_scene_count=10)
 path=out/"technical-qc-v1.json";save(path,report.model_dump(mode="json"));register("technical_qc",path)
 db.add_technical_check(VID,s.relative(target),report.passed,len(report.checks),report.model_dump(mode="json"))
 print("QC",report.passed,len(report.checks),report.blocking_issues,flush=True)
 print("PREVIEW",target,flush=True)
if __name__=="__main__":
 mode=sys.argv[1]
 if mode=="proofs":proofs()
 elif mode=="render":render()
 elif mode=="validate":
  inputs();print("INPUT VALIDATION PASSED")
 else:raise ValueError(mode)
