import sys, json, os
REPO=sys.argv[1]
sys.path.insert(0,REPO); sys.path.insert(0,REPO+"/tools"); sys.path.insert(0,REPO+"/oracle")
import numpy as np
import render_distortion_sse_fixtures as r
import oracle_common as oc
surgepy = oc.import_surgepy() if hasattr(oc,"import_surgepy") else __import__("surgepy")
sc=json.load(open(r.CONTROL_SIDECAR))
seq,_,_=r.rfx.rf.load_sequence(sc["sequence"]["id"])
buf,h,_=r.render_leg(surgepy, os.path.join(oc.engine_dir(), r.CONTROL_PRESET), seq, None)
import wave,struct
raw=open(REPO+"/"+sc["wet"]["wav"],"rb").read()
i=raw.find(b"data"); a=np.frombuffer(raw[i+8:],dtype="<f4")
b=np.asarray(buf,dtype=np.float32)
print(a.shape,b.shape, b.size)
b=b.T.reshape(-1) if b.shape[0]==2 else b.reshape(-1)
n=min(a.size,b.size); d=a[:n].astype(float)-b[:n]
print("max abs diff",abs(d).max(),"rms diff",np.sqrt((d**2).mean()),"rms ref",np.sqrt((a[:n].astype(float)**2).mean()), "first diff idx", int(np.argmax(d!=0)), "frac nonzero", (d!=0).mean())
