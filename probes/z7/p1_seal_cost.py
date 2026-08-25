#!/usr/bin/env python3
"""GATE7 Lane Z7 / PROBE 1 — cost of materialising a complete BaseTreeSnapshot.

READ-ONLY against whatever repo is passed. Streams `ls-tree -r -l HEAD` then
`cat-file --batch` and measures wall time + bytes for four storage strategies:

  metadata   : path, mode, blob oid, size, sha256(content)  -- NO content bytes
  raw        : content bytes written to a CAS keyed by blob oid
  zlib       : content bytes zlib-compressed into the same CAS
  hardlink   : (measured separately) reuse of git's own loose objects

Usage: p1_seal_cost.py <repo> [<pathspec-prefix>]
"""
import hashlib, os, subprocess, sys, time, zlib, json, tempfile, shutil

def run(argv, cwd, **kw):
    return subprocess.run(argv, cwd=cwd, capture_output=True, **kw)

def main():
    repo = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    out = {"repo": repo, "prefix": prefix}

    # ---- 1. enumerate ----
    t0 = time.perf_counter()
    argv = ["git", "ls-tree", "-r", "-l", "-z", "HEAD"]
    if prefix:
        argv += ["--", prefix]
    p = run(argv, repo)
    assert p.returncode == 0, p.stderr
    t_lstree = time.perf_counter() - t0

    entries = []
    for rec in p.stdout.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, otype, oid, size = meta.split()
        entries.append((mode.decode(), otype.decode(), oid.decode(), size.decode(), path))
    out["n_entries"] = len(entries)
    out["t_ls_tree_s"] = round(t_lstree, 4)
    out["declared_bytes"] = sum(int(e[3]) for e in entries if e[3] != b"-" and e[3] != "-")

    # ---- 2. stream every blob through cat-file --batch ----
    cas = tempfile.mkdtemp(prefix="z7cas-")
    cas_z = tempfile.mkdtemp(prefix="z7casz-")
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"], cwd=repo,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    req = b"".join((e[2] + "\n").encode() for e in entries)
    # write all requests first; safe here because we drain after, but a real
    # implementation MUST use a writer thread -- see failure-mode probe.
    import threading
    def _w():
        proc.stdin.write(req); proc.stdin.close()
    th = threading.Thread(target=_w); th.start()

    fh = proc.stdout
    raw_bytes = 0; z_bytes = 0; n_missing = 0
    hashes = {}
    metadata = []
    for e in entries:
        header = fh.readline()
        parts = header.split()
        if len(parts) == 2 and parts[1] == b"missing":
            n_missing += 1
            metadata.append({"path": e[4].decode("utf-8","surrogateescape"),
                             "mode": e[0], "oid": e[2], "status": "MISSING"})
            continue
        oid, otype, size = parts[0].decode(), parts[1].decode(), int(parts[2])
        buf = fh.read(size)
        assert fh.read(1) == b"\n"
        h = hashlib.sha256(buf).hexdigest()
        hashes[oid] = h
        metadata.append({"path": e[4].decode("utf-8","surrogateescape"),
                         "mode": e[0], "type": otype, "oid": oid,
                         "size": size, "sha256": h})
        # raw CAS
        d = os.path.join(cas, oid[:2])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, oid[2:]), "wb") as f:
            f.write(buf)
        raw_bytes += size
        # zlib CAS
        c = zlib.compress(buf, 6)
        d = os.path.join(cas_z, oid[:2])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, oid[2:]), "wb") as f:
            f.write(c)
        z_bytes += len(c)
    th.join(); proc.stdout.close(); proc.wait()
    t_seal = time.perf_counter() - t0

    out["t_catfile_seal_s"] = round(t_seal, 4)
    out["n_missing"] = n_missing
    out["raw_content_bytes"] = raw_bytes
    out["zlib_content_bytes"] = z_bytes
    meta_json = json.dumps(metadata, separators=(",", ":")).encode()
    out["metadata_only_bytes"] = len(meta_json)
    out["metadata_only_gz_bytes"] = len(zlib.compress(meta_json, 6))

    def du(p):
        tot = 0
        for r, _, fs in os.walk(p):
            for f in fs:
                tot += os.stat(os.path.join(r, f)).st_blocks * 512
        return tot
    out["raw_cas_disk_bytes"] = du(cas)
    out["zlib_cas_disk_bytes"] = du(cas_z)
    out["n_distinct_blobs"] = len(hashes)

    shutil.rmtree(cas); shutil.rmtree(cas_z)
    print(json.dumps(out, indent=2))

main()
