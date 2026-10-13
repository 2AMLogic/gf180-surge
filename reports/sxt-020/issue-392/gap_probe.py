import sys, json, hashlib, copy
sys.path.insert(0, ".")
from compiler import verify as V, compile as C
from tools.profile_predict import load_bundle_file, load_graphs, validate_spec
raw, b = load_bundle_file(V.REPO/"contracts"/"profile-v1-bundle-DRAFT.json")
_, obs, _ = load_graphs(V.REPO/"corpus"/"normalized"/"graphs.jsonl")
spec = validate_spec(b["B4-broad"], obs)
data = (V.GOLDEN_DIR/"compiled"/"four-fx-instance.image.bin").read_bytes()
p = C.parse_image(data)
h, body = p["header"], copy.deepcopy(p["body"])
al = body["derived"]["allocations"]
for blk in al["external_writable"]["blocks"]:
    if blk["slot"] == 5: blk["offset"] = 0
for e in al["fx_instances"]:
    if e["slot"] == 5: e["offset"] = 0
h = dict(h); h["body_sha256"] = hashlib.sha256(C.canonical_json(body)).hexdigest()
img = C.build_container(h, body)
ok, parsed = V.image_checks(img)
print("image ok", ok)
print("alloc ok", V.alloc_checks(parsed, spec))
