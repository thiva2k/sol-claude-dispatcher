#!/usr/bin/env python3
"""GATE7 Lane Z7 / PROBE 2 — raw git administrative-layout parser.

Resolves a worktree's repository identity by READING PLAIN FILES ONLY.
No `git` process is ever spawned. Intended to replace
`git rev-parse --show-toplevel` (git.py:271) and to be the PREPARE-time
sealing reader for the S-e (plumbing-file redirection) surface.

resolve(worktree_root) -> dict with:
    toplevel          canonical worktree root  (== rev-parse --show-toplevel)
    dotgit_kind       'dir' | 'file'
    gitdir            per-worktree admin dir   (== rev-parse --absolute-git-dir)
    commondir         shared admin dir         (== rev-parse --git-common-dir)
    object_stores     ordered list: primary store then every alternate,
                      transitively, with cycle protection
    head_raw          verbatim bytes of <gitdir>/HEAD
    head_target       symref target, or None if detached
    head_oid          resolved oid, WITHOUT running git
    identity_files    {relpath: sha256|ABSENT} over every load-bearing file
"""
from __future__ import annotations
import hashlib, os, sys, json
from pathlib import Path

class RawAdminError(Exception):
    pass

def _read(p: Path) -> bytes | None:
    try:
        return p.read_bytes()
    except (OSError, ValueError):
        return None

def _sha(b: bytes | None) -> str:
    return "ABSENT" if b is None else hashlib.sha256(b).hexdigest()

# ---------------------------------------------------------------- .git ------
def resolve_dotgit(worktree_root: Path) -> tuple[Path, str, bytes | None]:
    """worktree_root/.git -> (gitdir, kind, verbatim gitfile bytes|None)."""
    dot = worktree_root / ".git"
    if dot.is_dir():
        return dot, "dir", None
    if not dot.is_file():
        raise RawAdminError(f"no .git at {dot}")
    raw = dot.read_bytes()
    # git's setup.c: must start with exactly "gitdir: ", value is the rest of
    # the first line, trailing whitespace stripped.
    if not raw.startswith(b"gitdir: "):
        raise RawAdminError(f"gitfile has no 'gitdir: ' prefix: {raw[:40]!r}")
    line = raw[len(b"gitdir: "):].split(b"\n", 1)[0].rstrip()
    if not line:
        raise RawAdminError("gitfile gitdir value is empty")
    p = Path(os.fsdecode(line))
    if not p.is_absolute():
        p = (worktree_root / p)
    return Path(os.path.normpath(p)), "file", raw

# ----------------------------------------------------------- commondir ------
def resolve_commondir(gitdir: Path) -> tuple[Path, bytes | None]:
    raw = _read(gitdir / "commondir")
    if raw is None:
        return gitdir, None
    line = raw.split(b"\n", 1)[0].rstrip()
    p = Path(os.fsdecode(line))
    if not p.is_absolute():
        p = gitdir / p
    return Path(os.path.normpath(p)), raw

# -------------------------------------------------------- object stores -----
def resolve_object_stores(commondir: Path, gitdir: Path) -> list[dict]:
    """Primary store + every alternate, transitively. Mirrors git's
    link_alt_odb_entries(): one path per line, '#' comments ignored,
    relative paths are relative to THAT store's directory."""
    out, seen, queue = [], set(), []
    primary = Path(os.path.normpath(commondir / "objects"))
    queue.append((primary, "primary", None))
    while queue:
        store, why, via = queue.pop(0)
        key = str(store)
        if key in seen:
            continue
        seen.add(key)
        entry = {"path": key, "reason": why, "via": via,
                 "exists": store.is_dir()}
        out.append(entry)
        for name in ("alternates", "http-alternates"):
            af = store / "info" / name
            raw = _read(af)
            entry[name] = _sha(raw)
            if raw is None:
                continue
            entry[name + "_raw"] = raw.decode("utf-8", "replace")
            for ln in raw.split(b"\n"):
                ln = ln.strip()
                if not ln or ln.startswith(b"#"):
                    continue
                p = Path(os.fsdecode(ln))
                if not p.is_absolute():
                    p = store / p
                queue.append((Path(os.path.normpath(p)), name, str(af)))
    return out

# ---------------------------------------------------------------- HEAD ------
def _resolve_ref(name: str, gitdir: Path, commondir: Path, depth=0) -> str | None:
    if depth > 5:
        return None
    # per-worktree ref namespaces live in gitdir; everything else in commondir
    per_wt = name == "HEAD" or name.startswith(
        ("refs/bisect/", "refs/worktree/", "refs/rewritten/"))
    base = gitdir if per_wt else commondir
    raw = _read(base / name)
    if raw is not None:
        v = raw.split(b"\n", 1)[0].strip()
        if v.startswith(b"ref:"):
            return _resolve_ref(v[4:].strip().decode(), gitdir, commondir, depth + 1)
        return v.decode("ascii", "replace")
    # packed-refs (always in commondir)
    pr = _read(commondir / "packed-refs")
    if pr is not None:
        for ln in pr.split(b"\n"):
            if ln.startswith(b"#") or ln.startswith(b"^") or not ln.strip():
                continue
            parts = ln.split(b" ", 1)
            if len(parts) == 2 and parts[1].strip().decode() == name:
                return parts[0].decode("ascii", "replace")
    return None

# ------------------------------------------------- load-bearing inventory ---
# Every administrative file whose CHANGE alters repository, object-store or
# worktree identity.  Sol s14: nothing load-bearing may be exempted.
COMMON_IDENTITY_FILES = [
    "config", "config.worktree", "HEAD", "packed-refs", "shallow",
    "commondir",
    "objects/info/alternates", "objects/info/http-alternates",
    "objects/info/packs",
    "objects/info/commit-graph",
    "objects/info/multi-pack-index",
    "info/grafts", "info/attributes", "info/exclude", "info/sparse-checkout",
    "info/refs",
]
GITDIR_IDENTITY_FILES = [
    "gitdir", "commondir", "HEAD", "config.worktree", "index",
    "sparse-checkout", "info/sparse-checkout", "locked", "ORIG_HEAD",
]

def inventory(worktree_root: Path, gitdir: Path, commondir: Path) -> dict:
    inv = {}
    inv[".git@worktree"] = _sha(_read(worktree_root / ".git")) if (
        worktree_root / ".git").is_file() else "DIR"
    for rel in GITDIR_IDENTITY_FILES:
        inv["gitdir/" + rel] = _sha(_read(gitdir / rel))
    for rel in COMMON_IDENTITY_FILES:
        inv["common/" + rel] = _sha(_read(commondir / rel))
    # refs/replace/** -- object substitution, honoured by cat-file/ls-tree
    rr = commondir / "refs" / "replace"
    reps = []
    if rr.is_dir():
        for r, _, fs in os.walk(rr):
            for f in sorted(fs):
                fp = Path(r) / f
                reps.append(str(fp.relative_to(commondir)) + "=" +
                            (_read(fp) or b"").decode("ascii", "replace").strip())
    # packed replace refs too
    pr = _read(commondir / "packed-refs")
    if pr:
        for ln in pr.split(b"\n"):
            if b" refs/replace/" in ln:
                reps.append(ln.decode("ascii", "replace").strip())
    inv["common/refs/replace/**"] = _sha("\n".join(sorted(reps)).encode()) if reps else "ABSENT"
    inv["_replace_refs"] = reps
    # every other registered worktree's pointer files
    wt = commondir / "worktrees"
    if wt.is_dir():
        for d in sorted(os.listdir(wt)):
            for rel in ("gitdir", "commondir", "HEAD"):
                inv[f"common/worktrees/{d}/{rel}"] = _sha(_read(wt / d / rel))
    # hooks: presence + content of every executable hook
    hk = commondir / "hooks"
    if hk.is_dir():
        hs = sorted(f for f in os.listdir(hk) if not f.endswith(".sample"))
        inv["common/hooks/**"] = _sha(("\n".join(
            f"{f}:{_sha(_read(hk / f))}" for f in hs)).encode()) if hs else "EMPTY"
    return inv

def resolve(worktree_root: str | Path) -> dict:
    wt = Path(worktree_root).resolve()
    gitdir, kind, gitfile_raw = resolve_dotgit(wt)
    commondir, commondir_raw = resolve_commondir(gitdir)
    head_raw = _read(gitdir / "HEAD")
    head_target = None
    if head_raw and head_raw.split(b"\n", 1)[0].strip().startswith(b"ref:"):
        head_target = head_raw.split(b"\n", 1)[0].strip()[4:].strip().decode()
    res = {
        "toplevel": str(wt),
        "dotgit_kind": kind,
        "gitfile_raw": gitfile_raw.decode("utf-8", "replace") if gitfile_raw else None,
        "gitdir": str(gitdir),
        "commondir": str(commondir),
        "commondir_raw": commondir_raw.decode("utf-8", "replace") if commondir_raw else None,
        "object_stores": resolve_object_stores(commondir, gitdir),
        "head_raw": head_raw.decode("utf-8", "replace").strip() if head_raw else None,
        "head_target": head_target,
        "head_oid": _resolve_ref("HEAD", gitdir, commondir),
        "identity_files": inventory(wt, gitdir, commondir),
    }
    # back-link check: worktrees/<id>/gitdir must point at OUR .git file
    if kind == "file":
        back = _read(gitdir / "gitdir")
        res["backlink"] = back.decode().strip() if back else None
        res["backlink_ok"] = (res["backlink"] == str(wt / ".git"))
    # store count > 1 means an alternate is in play
    res["alternate_store_count"] = len(res["object_stores"]) - 1
    return res

if __name__ == "__main__":
    print(json.dumps(resolve(sys.argv[1]), indent=2, sort_keys=True))
