#!/usr/bin/env python3
"""Z17 commit-graph forger. Re-parents HEAD onto a decoy orphan inside a
single-file objects/info/commit-graph, recomputing the trailing SHA-1.

Every step asserts. A forger that silently no-ops is the failure mode this gate
has hit four times, so this one REFUSES rather than returning an unforged repo.
"""
import hashlib, os, struct, subprocess

GIT = "/usr/bin/git"

def write_graph(root, env, commits):
    p = subprocess.run([GIT, "commit-graph", "write", "--stdin-commits"],
                       cwd=root, env=env, input="\n".join(commits) + "\n",
                       capture_output=True, text=True)
    assert p.returncode == 0, f"commit-graph write: {p.returncode} {p.stderr}"
    path = os.path.join(root, ".git", "objects", "info", "commit-graph")
    assert os.path.exists(path), "single-file commit-graph was not produced"
    return path

def parse(path):
    b = bytearray(open(path, "rb").read())
    assert b[0:4] == b"CGPH", f"bad magic {b[0:4]!r}"
    version, hashver, nchunks = b[4], b[5], b[6]
    assert version == 1 and hashver == 1, f"unsupported v{version} h{hashver}"
    chunks = {}
    off = 8
    entries = []
    for i in range(nchunks + 1):
        cid = bytes(b[off:off+4]); coff = struct.unpack(">Q", b[off+4:off+12])[0]
        entries.append((cid, coff)); off += 12
    for i in range(nchunks):
        cid, coff = entries[i]
        chunks[cid] = (coff, entries[i+1][1] - coff)
    return b, chunks

def forge(path, head_hex, decoy_hex):
    b, chunks = parse(path)
    assert b"OIDL" in chunks and b"CDAT" in chunks, f"chunks: {list(chunks)}"
    ol_off, ol_len = chunks[b"OIDL"]
    n = ol_len // 20
    oids = [b[ol_off + i*20: ol_off + (i+1)*20].hex() for i in range(n)]
    assert head_hex in oids, f"HEAD {head_hex[:8]} NOT IN GRAPH (have {[o[:8] for o in oids]})"
    assert decoy_hex in oids, f"DECOY {decoy_hex[:8]} NOT IN GRAPH (have {[o[:8] for o in oids]})"
    hi, di = oids.index(head_hex), oids.index(decoy_hex)
    cd_off, cd_len = chunks[b"CDAT"]
    assert cd_len // 36 == n, f"CDAT {cd_len} not {n}*36"
    ent = cd_off + hi*36
    before = struct.unpack(">I", b[ent+20:ent+24])[0]
    b[ent+20:ent+24] = struct.pack(">I", di)
    after = struct.unpack(">I", b[ent+20:ent+24])[0]
    assert after == di and after != before, \
        f"PARENT1 PATCH DID NOT TAKE: {before} -> {after}, wanted {di}"
    body = bytes(b[:-20])
    b[-20:] = hashlib.sha1(body).digest()
    # 0444 file in a directory we own: unlink then rewrite
    os.chmod(path, 0o644)
    os.unlink(path)
    with open(path, "wb") as f:
        f.write(bytes(b))
    os.chmod(path, 0o444)
    reread = open(path, "rb").read()
    assert reread == bytes(b), "REWRITE DID NOT TAKE — file on disk differs"
    return {"n": n, "head_idx": hi, "decoy_idx": di, "parent1": f"{before}->{after}"}
