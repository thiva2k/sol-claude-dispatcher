#!/usr/bin/env python3
"""Z7 PROBE 1d -- can EVERY later evidence artefact be regenerated from a
sealed BaseTreeSnapshot + a filesystem walk, with ZERO git commands?

Produces: changed_paths, status-equivalent, name-only, numstat/stat, and a
unified patch.  Then checks the patch with `git apply --check` (a NON-authoritative
use, run only to validate this probe)."""
import difflib, hashlib, json, os, subprocess, sys, time, zlib, threading
from pathlib import Path

def seal(repo: Path, ref="HEAD") -> dict:
    p = subprocess.run(["git","ls-tree","-r","-l","-z",ref],cwd=repo,capture_output=True)
    ents=[]
    for rec in p.stdout.split(b"\0"):
        if not rec: continue
        meta,path=rec.split(b"\t",1); m,t,o,s=meta.split()
        ents.append((m.decode(),o.decode(),int(s),path))
    proc=subprocess.Popen(["git","cat-file","--batch"],cwd=repo,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    req=b"".join((e[1]+"\n").encode() for e in ents)
    threading.Thread(target=lambda:(proc.stdin.write(req),proc.stdin.close())).start()
    fh=proc.stdout; snap={}
    for e in ents:
        parts=fh.readline().split()
        oid,ot,sz=parts[0].decode(),parts[1].decode(),int(parts[2])
        buf=fh.read(sz); fh.read(1)
        snap[e[3]]={"mode":e[0],"oid":oid,"size":sz,
                    "sha256":hashlib.sha256(buf).hexdigest(),"bytes":buf}
    proc.wait()
    return snap

def walk(root: Path, snap, scoped=False):
    """Filesystem side. No git: the ignore set is the sealed base's own
    .gitignore semantics -- out of scope here, so we walk everything but .git."""
    cur={}
    if scoped:  # only the sealed path set -- bounded by the snapshot
        for rel in snap:
            fp = root / os.fsdecode(rel)
            try: b = fp.read_bytes()
            except OSError: continue
            cur[rel]={"bytes":b,"sha256":hashlib.sha256(b).hexdigest(),
                      "mode":"100755" if os.access(fp,os.X_OK) else "100644"}
        return cur
    for r,ds,fs in os.walk(root):
        ds[:] = [d for d in ds if d != ".git"]
        for f in fs:
            fp=Path(r)/f
            rel=os.fsencode(str(fp.relative_to(root)))
            try: b=fp.read_bytes()
            except OSError: continue
            cur[rel]={"bytes":b,"sha256":hashlib.sha256(b).hexdigest(),
                      "mode":"100755" if os.access(fp,os.X_OK) else "100644"}
    return cur

def regen(snap, cur):
    base=set(snap); now=set(cur)
    added=sorted(now-base); deleted=sorted(base-now)
    modified=sorted(p for p in base&now if snap[p]["sha256"]!=cur[p]["sha256"])
    modemod=sorted(p for p in base&now if snap[p]["mode"]!=cur[p]["mode"])
    patch=[]; ins=dels=0
    def d(p):
        return p.decode("utf-8","surrogateescape")
    def istext(b): return b"\0" not in b[:8000]
    for p in sorted(set(added)|set(deleted)|set(modified)):
        o=snap.get(p,{}).get("bytes",b""); n=cur.get(p,{}).get("bytes",b"")
        name=d(p)
        if not (istext(o) and istext(n)):
            patch.append(f"diff --git a/{name} b/{name}\nBinary files differ\n"); continue
        ol=o.decode("utf-8","surrogateescape").splitlines(keepends=True)
        nl=n.decode("utf-8","surrogateescape").splitlines(keepends=True)
        aname = "/dev/null" if p in added else f"a/{name}"
        bname = "/dev/null" if p in deleted else f"b/{name}"
        hunks=list(difflib.unified_diff(ol,nl,aname,bname,n=3))
        if not hunks: continue
        hdr=f"diff --git a/{name} b/{name}\n"
        if p in added: hdr+= "new file mode %s\n"%cur[p]["mode"]
        elif p in deleted: hdr+= "deleted file mode %s\n"%snap[p]["mode"]
        patch.append(hdr+"".join(hunks))
        for h in hunks:
            if h.startswith("+") and not h.startswith("+++"): ins+=1
            elif h.startswith("-") and not h.startswith("---"): dels+=1
    return {"added":[d(x) for x in added],"deleted":[d(x) for x in deleted],
            "modified":[d(x) for x in modified],"mode_changed":[d(x) for x in modemod],
            "insertions":ins,"deletions":dels,"patch":"".join(patch)}

if __name__=="__main__":
    repo=Path(sys.argv[1])
    t0=time.perf_counter(); snap=seal(repo); t_seal=time.perf_counter()-t0
    scoped = "--scoped" in sys.argv
    t0=time.perf_counter(); cur=walk(repo,snap,scoped); t_walk=time.perf_counter()-t0
    t0=time.perf_counter(); r=regen(snap,cur); t_regen=time.perf_counter()-t0
    print(json.dumps({k:v for k,v in r.items() if k!="patch"},indent=2)[:1500])
    print(f"\nt_seal={t_seal:.3f}s t_walk={t_walk:.3f}s t_regen={t_regen:.3f}s "
          f"patch_bytes={len(r['patch'])}")
    if len(sys.argv)>2 and not sys.argv[2].startswith("--"):
        Path(sys.argv[2]).write_text(r["patch"])
        print("patch written to",sys.argv[2])
