from pathlib import Path
import sys,json,hashlib,time
import numpy as np
ROOT=Path.cwd()
sys.path.insert(0,str(ROOT))
from midnight_archive.config import Settings
from midnight_archive.models import Script
from midnight_archive.voiceover import voice_info,write_wav
from kokoro_onnx import Kokoro
work=ROOT/'work/rhythm-review-v1'
work.mkdir(parents=True,exist_ok=True)
settings=Settings.load(ROOT)
script_path=next((ROOT/'output/scripts').glob('TMA-0001-*-v3.json'))
script=Script.model_validate_json(script_path.read_text(encoding='utf-8'))
info=voice_info(settings,'bm_george')
protected=[p for folder in ['output','config','midnight_archive','data','tests'] for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in str(p)]
hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
(work/'before.json').write_text(json.dumps(hashes,indent=2))
client=Kokoro(str(info.model_path),str(info.voices_path))
groups=[(1,3),(4,4),(5,8),(9,9),(10,11),(12,13)]
records=[]
for index,(first,last) in enumerate(groups,1):
 display=' '.join(b.text for b in script.narration[first-1:last])
 spoken=display.replace('3:07','three-oh-seven')
 start=time.perf_counter()
 samples,rate=client.create(spoken,voice='bm_george',speed=0.96,lang='en-gb',sentence_pause=0.18,clause_pause=0.08)
 path=work/f'group-{index}-raw.wav'
 if path.exists(): raise RuntimeError('Refuse overwrite')
 write_wav(path,np.asarray(samples,dtype=np.float32),rate)
 record={'group':index,'first_beat':first,'last_beat':last,'display':display,'spoken':spoken,'seconds':len(samples)/rate,'generation_seconds':time.perf_counter()-start,'phonemes':client.tokenizer.phonemize(spoken,'en-gb')}
 records.append(record)
 print(json.dumps({k:v for k,v in record.items() if k not in ['phonemes','display','spoken']}),flush=True)
(work/'groups.json').write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
print('TOTAL_RAW',sum(r['seconds'] for r in records),flush=True)
