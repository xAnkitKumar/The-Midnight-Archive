"""Build one isolated review candidate from six connected Kokoro passages."""
from pathlib import Path
import sys,json,hashlib,re,difflib,subprocess,importlib.metadata
import numpy as np
ROOT=Path.cwd()
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'experiments'))
from midnight_archive.config import Settings
from midnight_archive.models import Script,WordTiming
from midnight_archive.voiceover import read_wav,write_wav,master_narration,voice_info,BeatAudio,NarrationPlan
from midnight_archive.subtitles import WhisperAligner,WordCue,display_tokens,align_beat_tokens,build_cues,validate_cues,write_srt,write_ass,SubtitleStyle,parse_srt
from narration_review import _loudness,_transcribe
work=ROOT/'work/rhythm-review-v1'
settings=Settings.load(ROOT)
script_path=next((ROOT/'output/scripts').glob('TMA-0001-*-v3.json'))
script=Script.model_validate_json(script_path.read_text(encoding='utf-8'))
records=json.loads((work/'groups.json').read_text(encoding='utf-8'))
parent=ROOT/'output/narration_review/TMA-0001-v3-bm_george'
out=parent/'v4-rhythm'
out.mkdir(parents=True,exist_ok=False)
rate=24000
# Group boundaries correspond to actual narrative turns, not every sentence.
pauses=[0.75,0.25,0.30,0.80,0.70,0.65]
head=0.25
parts=[np.zeros(round(head*rate),dtype=np.float32)]
cursor=len(parts[0])
for r,gap in zip(records,pauses):
 a,sr,_=read_wav(work/f"group-{r['group']}-raw.wav")
 assert sr==rate and np.isfinite(a).all()
 fade=min(round(.005*rate),len(a)//2)
 a[:fade]*=np.linspace(0,1,fade)
 a[-fade:]*=np.linspace(1,0,fade)
 r.update(start_sample=cursor,end_sample=cursor+len(a),pause_after_s=gap)
 parts.extend([a,np.zeros(round(gap*rate),dtype=np.float32)])
 cursor+=len(a)+round(gap*rate)
full=master_narration(np.concatenate(parts),rate,settings)
audio=out/'narration-v4.wav'
write_wav(audio,full,rate)
duration=len(full)/rate
print('DURATION',duration,flush=True)

def canonical_time(words):
    result=[]; changes=[]; i=0
    while i<len(words):
        found=False
        for count in (3,2,1):
            seq=words[i:i+count]
            joined=''.join(re.sub('[^a-z0-9]','',w[0].lower()) for w in seq)
            if len(seq)==count and joined in {'threeohseven','threezeroseven','307','3oh7','3o7'}:
                result.append(('3:07',seq[0][1],seq[-1][2]))
                changes.append({'original':[w[0] for w in seq],'mapped':'3:07'})
                i+=count;found=True;break
        if not found: result.append(words[i]);i+=1
    return result,changes

aligner=WhisperAligner()
all_words=[]; recognitions=[]; interpolation=[]
for r in records:
 start,end=r['start_sample'],r['end_sample']
 detected=aligner._recognise(full[start:end],rate)
 if not detected: raise RuntimeError('No recognised words in group')
 mapped,changes=canonical_time(detected)
 tokens=display_tokens(r['display'])
 cues=align_beat_tokens(tokens,mapped,start/rate,(end-start)/rate)
 beat_ids=[b.beat for b in script.narration[r['first_beat']-1:r['last_beat']] for _ in display_tokens(b.text)]
 assert len(cues)==len(beat_ids)
 all_words.extend(WordCue(w.word,w.start,w.end,beat) for w,beat in zip(cues,beat_ids))
 norm=lambda t:re.sub(r"[^\w'-]",'',t.lower())
 matches=difflib.SequenceMatcher(a=[norm(t) for t in tokens],b=[norm(w[0]) for w in mapped],autojunk=False)
 exact={j for block in matches.get_matching_blocks() for j in range(block.a,block.a+block.size)}
 interpolation.append({'group':r['group'],'interpolated_tokens':[t for j,t in enumerate(tokens) if j not in exact]})
 recognitions.append({'group':r['group'],'words':detected,'time_mappings':changes})
 print('ALIGNED',r['group'],' '.join(w[0] for w in detected),flush=True)
assert ' '.join(w.word for w in all_words)==script.plain_text
assert all(w.start>=0 and w.end>w.start and w.end<=duration for w in all_words)
assert all(a.end<=b.start+.001 for a,b in zip(all_words,all_words[1:]))
cues=build_cues(all_words)
issues=validate_cues(cues,all_words)
assert not issues,issues
assert cues[-1].end<=duration
write_srt(cues,out/'subtitles-v4.srt')
write_ass(cues,out/'subtitles-v4.ass',SubtitleStyle.from_settings(settings))
assert ' '.join(c.text.replace('\n',' ') for c in parse_srt(out/'subtitles-v4.srt'))==script.plain_text
method='fresh faster-whisper base.en timestamps per connected passage; authored-token mapping with disclosed interpolation'
alignment={'method':method,'words':[vars(w) for w in all_words],'cues':[vars(c) for c in cues],'recognitions':recognitions,'interpolation':interpolation,'text_matches_script':True,'word_count':len(all_words)}
(out/'alignment-v4.json').write_text(json.dumps(alignment,indent=2),encoding='utf-8')
beats=[]
for b in script.narration:
 ws=[w for w in all_words if w.beat==b.beat]
 beats.append(BeatAudio(b.beat,b.text,ws[0].start,ws[-1].end,full[round(ws[0].start*rate):round(ws[-1].end*rate)]))
info=voice_info(settings,'bm_george')
plan=NarrationPlan('kokoro',info,rate,full,beats)
metadata=plan.metadata('TMA-0001',length_scale=.96,words=[WordTiming(**vars(w)) for w in all_words],alignment_method=method)
(out/'narration-metadata-v4.json').write_text(metadata.model_dump_json(indent=2),encoding='utf-8')

def silences(path):
 r=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-i',str(path),'-af','silencedetect=noise=-45dB:d=0.20','-f','null','-'],check=True,capture_output=True,text=True)
 starts=[float(x) for x in re.findall(r'silence_start:\s*([\d.]+)',r.stderr)]
 ends=[float(x) for x in re.findall(r'silence_end:\s*([\d.]+)',r.stderr)]
 return [{'start':s,'end':e,'duration':round(e-s,4)} for s,e in zip(starts,ends)]
old=parent/'v3/narration.wav'
new_gaps=silences(audio);old_gaps=silences(old)
transcript=_transcribe(full,rate,settings)
lufs,tp=_loudness(audio)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=json.loads((work/'before.json').read_text())
changed=[p for p,h in before.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
suspense=[]
for index,label in [(0,'He was alive.'),(3,'Different name.'),(4,"His name. Mara's.")]:
 r=records[index]
 boundary=r['end_sample']/rate
 matches=[g for g in new_gaps if g['start']<=boundary+.1 and g['end']>=boundary]
 suspense.append({'after':label,'boundary':boundary,'added_gap':r['pause_after_s'],'detected_gap':matches})
qc={'review_only':True,'human_approval_required':True,'duration':duration,'previous_duration':len(read_wav(old)[0])/rate,'speed':.96,'voice':'bm_george','language':'en-gb','model_sha256':sha(info.model_path),'voice_bank_sha256':sha(info.voices_path),'script_sha256':sha(script_path),'generation_groups':records,'source_wording_unchanged':True,'displayed_text_unchanged':True,'spoken_substitution':{'3:07':'three-oh-seven'},'names_spelling_changed':False,'new_pauses':new_gaps,'previous_pauses':old_gaps,'suspense':suspense,'integrated_lufs':lufs,'true_peak_dbtp':tp,'clipping_samples':int(np.count_nonzero(np.abs(full)>=.999)),'transcript':transcript,'alignment_interpolation':interpolation,'protected_existing_files_changed':changed,'packages':{p:importlib.metadata.version(p) for p in ['kokoro-onnx','onnxruntime','faster-whisper','numpy']},'checks':{'duration_55_58':55<=duration<=58,'subtitle_text_exact':True,'word_timings_ordered':True,'subtitle_cues_valid':not issues,'no_existing_files_changed':not changed,'suspense_gaps_present':all(x['detected_gap'] for x in suspense)}}
(out/'review-qc-v4.json').write_text(json.dumps(qc,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({k:qc[k] for k in ['duration','previous_duration','integrated_lufs','true_peak_dbtp','transcript','checks','suspense','alignment_interpolation']},indent=2),flush=True)
print('WROTE',out,flush=True)
