import sys
sys.path.insert(0, ".")
from compiler import verify as V
from tools.profile_predict import load_bundle_file, load_graphs, validate_spec
raw, b = load_bundle_file(V.REPO/"contracts"/"profile-v1-bundle-DRAFT.json")
_, obs, _ = load_graphs(V.REPO/"corpus"/"normalized"/"graphs.jsonl")
spec = validate_spec(b["B4-broad"], obs)
def reverse_packing(al):
    offsets = {5: 0, 4: 2228224}
    for b in al['external_writable']['blocks']:
        b['offset'] = offsets[b['slot']]
    for e in al['fx_instances']:
        if e['slot'] in offsets:
            e['offset'] = offsets[e['slot']]
def dup(al):
    al['fx_instances'].append(dict(al['fx_instances'][0]))
for name, mutate in (("reverse_packing", reverse_packing),
                     ("empty", lambda al: al.update(fx_instances=[])),
                     ("duplicate", dup)):
    res = V._quiet_verify(V._mutated_image(V.GOLDEN_DIR, mutate), spec)
    print(name, "FAILED:", [n for n, v in res.items() if not v])
