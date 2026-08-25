#!/usr/bin/env python3
"""Z7 PROBE 1b — separate the cost of each sealing strategy.
Modes: hash (stream+sha256, no store) | raw | zlib | packfile
Usage: p1b_modes.py <repo> <mode> [prefix]"""
import hashlib,os,subprocess,sys,time,zlib,json,tempfile,shutil,threading

repo=sys.argv[1]; mode=sys.argv[2]; prefix=sys.argv[3] if len(sys.argv)>3 else None

argv=["git","ls-tree","-r","-l","-z","HEAD"]+ (["--",prefix] if prefix else [])
t0=time.perf_counter()
p=subprocess.run(argv,cwd=repo,capture_output=True); assert p.returncode==0,p.stderr
ents=[]
for rec in p.stdout.split(b"\0"):
    if not rec: continue
    meta,path=rec.split(b"\t",1); m,t,o,s=meta.split()
    ents.append((m.decode(),t.decode(),o.decode(),s.decode(),path))
t_ls=time.perf_counter()-t0

store=tempfile.mkdtemp(prefix="z7-"+mode+"-")
t0=time.perf_counter()

if mode=="packfile":
    # Alternative: ask git itself for one immutable pack containing the whole base
    pk=subprocess.run(["git","pack-objects","--revs","--stdout","-q"],cwd=repo,
        input=b"HEAD\n",capture_output=True)
    assert pk.returncode==0,pk.stderr[-500:]
    with open(os.path.join(store,"base.pack"),"wb") as f: f.write(pk.stdout)
    t_seal=time.perf_counter()-t0
    n=len(pk.stdout); stored=n; nblob=len(ents)
else:
    proc=subprocess.Popen(["git","cat-file","--batch"],cwd=repo,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    req=b"".join((e[2]+"\n").encode() for e in ents)
    th=threading.Thread(target=lambda:(proc.stdin.write(req),proc.stdin.close()));th.start()
    fh=proc.stdout; stored=0; seen=set()
    for e in ents:
        parts=fh.readline().split()
        if len(parts)==2: continue
        oid,ot,sz=parts[0].decode(),parts[1].decode(),int(parts[2])
        buf=fh.read(sz); fh.read(1)
        hashlib.sha256(buf).hexdigest()
        if mode=="hash" or oid in seen: 
            seen.add(oid); continue
        seen.add(oid)
        data=zlib.compress(buf,6) if mode=="zlib" else buf
        d=os.path.join(store,oid[:2]); os.makedirs(d,exist_ok=True)
        with open(os.path.join(d,oid[2:]),"wb") as f: f.write(data)
        stored+=len(data)
    th.join(); proc.stdout.close(); proc.wait()
    t_seal=time.perf_counter()-t0; nblob=len(seen)

def du(pth):
    tot=0
    for r,_,fs in os.walk(pth):
        for f in fs: tot+=os.stat(os.path.join(r,f)).st_blocks*512
    return tot
res={"repo":repo,"prefix":prefix,"mode":mode,"n_entries":len(ents),
     "n_distinct":nblob,"declared_bytes":sum(int(e[3]) for e in ents if e[3]!="-"),
     "t_ls_tree_s":round(t_ls,4),"t_seal_s":round(t_seal,4),
     "stored_logical_bytes":stored,"store_disk_bytes":du(store)}
shutil.rmtree(store)
print(json.dumps(res))
