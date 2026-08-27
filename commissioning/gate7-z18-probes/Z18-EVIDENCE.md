# GATE 7 REVISION 9 — LANE Z18 EVIDENCE

Committed experimental evidence for two of the three sixth-revision blockers:
**F7-3** (the dead positive control in the PATH experiment) and **F7-2** (the
multi-pack-index path), plus the committed demonstration **F7-1** needs.

Every claim below is backed by a source-controlled probe in this directory and
its preserved output. Labels are **MEASURED**, **NOT TESTED**, or **NOT
ATTEMPTED**. `NOT TESTABLE` is a banned label and does not appear.

## Provenance

| | |
|---|---|
| Base commit | `9a5554675c4affe14233852f2194516cf8bb5334` |
| Command | `bash commissioning/gate7-z18-probes/run.sh` |
| Run (UTC) | `2026-08-27T18:20:45Z` |
| Host | Ubuntu 24.04.3 LTS, Linux 6.8.0-71-generic x86_64 |
| git | `/usr/bin/git`, **git version 2.43.0** |
| python | `/usr/bin/python3`, **3.12.3** |
| `/bin/sh` | `/usr/bin/dash`, dash 0.5.12-6ubuntu5 |
| Full environment capture | `environment.txt` |
| Per-probe exit codes | `exit-codes.txt` — all repaired probes exit `0` |

`docs/GATE7-DESIGN.md`, `src/**` and `tests/**` were not read for edit and not
modified by this lane. Every probe operates only inside a `mktemp -d` scratch
directory it creates and deletes.

---

## F7-3 — the PATH experiment had a DEAD POSITIVE CONTROL, and now does not

### The defect, preserved

`commissioning/gate7-z17-probes/exp8_path.py` is committed **unmodified**; its
transcript is preserved verbatim at `exp8_ORIGINAL_dead_control.stdout.txt`:

```
  PATH ADMITTED (contains the filter program)    rc=0 filter_EXECUTED=False f.txt='payload'
      stderr: /tmp/z17pbin.ta51anak/z17filter: 2: touch: not found
  PATH ADMITTED (normal system PATH)             rc=0 filter_EXECUTED=False f.txt='payload'
      stderr: error: cannot run z17filter: No such file or directory
  PATH DENIED   (Sol's allowlist without PATH)   rc=0 filter_EXECUTED=False f.txt='payload'
      stderr: error: cannot run z17filter: No such file or directory
```

The helper is given `PATH=<shimdir>` and then calls the external programs
`touch` and `cat`, neither of which is resolvable under that very PATH. The
shim dies on its first line; the marker is never written; **all three legs read
`filter_EXECUTED=False`, so all three legs are indistinguishable.** The probe's
own closing text says the experiment proves nothing unless the first leg reads
True — it never has.

**A second, separate defect:** that probe **exits 0** with its control dead
(`exit-codes.txt`). It does not fail loudly, which is how a dead control
survives into a revision as a prose claim.

Revision 8's claim of a corrected run producing `filter EXECUTED=TRUE` is
**NOT ATTEMPTED to be reproduced from revision 8's artefacts** — no corrected
probe and no output were committed, so there was nothing to re-run. The result
below is a fresh, independently constructed measurement.

### The repair — `exp8b_path_fixed.py`

Two changes, both required:

1. **The helper no longer depends on commands excluded by its own PATH.**
   Shim A uses **only shell built-ins and redirection**:
   `#!/bin/sh` · `: > "$MARK"` (marker by redirection) · `echo HOSTILE_SMUDGE_RAN`.
   `:` and `echo` are dash built-ins (verified: `type :` → *"is a special shell
   builtin"*, `type echo` → *"is a shell builtin"*). Shim B is the alternative
   construction the brief permits — external programs named by **absolute paths
   the probe measures at run time** (`/usr/bin/touch`, `/usr/bin/cat` via
   `shutil.which`).
2. **The positive control changes an observable result**, not just a marker.
   Shim A replaces the checked-out content of `f.txt`, so the hostile leg is
   visible in the worktree independently of the marker file.

`git` is invoked at an **absolute path resolved by measurement**
(`shutil.which("git")` → `realpath` → `/usr/bin/git`), which the probe
cross-checks against Z17's hard-coded `rows.GIT` (**agrees=True**). The pin
block is imported from `rows.pin_block`, so it is byte-identical to Z17's.

**The probe fails loudly.** If leg A does not fire it prints `CONTROL FAILURE`
and exits `2`; a breached defended leg exits `3`. Only an exit of `0` licenses
citing it.

### Both legs — verbatim from `exp8b_path_fixed.stdout.txt`

```
  [A] POSITIVE CONTROL — hostile PATH admitted, built-ins-only shim
      child env  : ['GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM', 'GIT_NO_LAZY_FETCH', 'GIT_NO_REPLACE_OBJECTS', 'GIT_OPTIONAL_LOCKS', 'GIT_TERMINAL_PROMPT', 'PATH']
      PATH       : '/tmp/z18bin.ebp4u3j5'
      repo cfg   : filter.z18.smudge = 'z18filter'
      displaced  : []
      argv[0]    : '/usr/bin/git'  (absolute=True)
      -> rc=0  filter_EXECUTED=True  f.txt='HOSTILE_SMUDGE_RAN'
      EXPECTED filter_EXECUTED=True  ->  AS EXPECTED

  [A2] POSITIVE CONTROL 2 — hostile PATH admitted, MEASURED-ABSOLUTE shim (pass-through: marker is the only signal)
      -> rc=0  filter_EXECUTED=True  f.txt='payload'
      EXPECTED filter_EXECUTED=True  ->  AS EXPECTED

  [B] PATH admitted but ORDINARY (shim not on it) — resolution is PATH-directed
      -> rc=0  filter_EXECUTED=False  f.txt='payload'
      stderr[0]: error: cannot run z18filter: No such file or directory
      stderr[1]: error: cannot fork to run external filter 'z18filter'
      stderr[2]: error: external filter 'z18filter' failed
      EXPECTED filter_EXECUTED=False  ->  AS EXPECTED

  [C] DEFENDED CONTROL — final child env (allowlist, NO PATH) + absolute git executable
      child env  : ['GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM', 'GIT_NO_LAZY_FETCH', 'GIT_NO_REPLACE_OBJECTS', 'GIT_OPTIONAL_LOCKS', 'GIT_TERMINAL_PROMPT']
      PATH       : '(ABSENT)'
      repo cfg   : filter.z18.smudge = 'z18filter'
      displaced  : []
      argv[0]    : '/usr/bin/git'  (absolute=True)
      -> rc=0  filter_EXECUTED=False  f.txt='payload'
      stderr[0]: error: cannot run z18filter: No such file or directory
      stderr[1]: error: cannot fork to run external filter 'z18filter'
      stderr[2]: error: external filter 'z18filter' failed
      EXPECTED filter_EXECUTED=False  ->  AS EXPECTED
```

Verdict block, verbatim:

```
  POSITIVE CONTROL A  : executed=True content='HOSTILE_SMUDGE_RAN' -> FIRED
  POSITIVE CONTROL A2 : executed=True content='payload' -> FIRED
  DEFENDED CONTROL C  : executed=False content='payload' rc=0 -> HELD
  BOUNDARY D (absolute-path smudge, no PATH) : executed=True content='HOSTILE_SMUDGE_RAN'
  BOUNDARY E (displaced argv, no PATH)       : executed=True content='HOSTILE_SMUDGE_RAN'
```

**MEASURED.** On git 2.43.0, `git worktree add --detach` runs an in-tree
`.gitattributes` **smudge filter driver** during checkout. With a hostile
`PATH` admitted the driver **executes** (marker written) and **changes the
checked-out content** (`payload` → `HOSTILE_SMUDGE_RAN`). With the final child
environment — the allowlist and nothing else, no `PATH` — the same repository,
the same in-tree `.gitattributes` and the same repository config produce
**no execution and the original content**, at `rc=0`.

Note the pin block's `core.attributesFile=/dev/null` neutralises the **global**
attributes file only. The **in-tree** `.gitattributes` is still honoured. That
is why this surface exists at all, and it is why the defence has to come from
the child environment rather than from the pin block.

### What this experiment could have detected but did not

* that `worktree add` does not run smudge filters at all — leg A refutes it;
* that a bare-name smudge program is resolved by something other than the
  child's `PATH` — leg B (ordinary PATH, shim absent from it) refutes it;
* that the final child-environment construction fails to suppress a
  repository-supplied filter driver — leg C refutes it;
* that `git` cannot be invoked at all without `PATH` — the T-40 leg refutes it.

### THREE DISTINCTIONS THAT MUST NOT COLLAPSE

**(1) The environment allowlist closes INHERITED ENVIRONMENT VARIABLES.**
That, and only that, is what leg C shows. `PATH` is absent from the child, so a
bare-name filter program has nowhere to resolve from.

**(2) It does NOT close displaced argv `git -c` injection — ZI-71 REMAINS
REQUIRED.** Leg E is the measurement. Child env is the full allowlist with **no
`PATH`**; the repository config is **clean** (`filter.z18.smudge = None`); the
only hostile input is a caller-contributed argv element placed **before** the
pin block:

```
      displaced  : ['-c', 'filter.z18.smudge=/tmp/z18bin.ebp4u3j5/z18filter', '-c', 'filter.z18.required=false']
      PATH       : '(ABSENT)'
      -> rc=0  filter_EXECUTED=True  f.txt='HOSTILE_SMUDGE_RAN'
```

**MEASURED — the argv half of the hazard is untouched by the environment
allowlist.** An implementer who reads *"the env hazard is gone"* and relaxes
`PIN_BLOCK`'s closed, ordered, terminal-prefix invariant re-opens this exact
execution. **ZI-71 is not retired by the allowlist's success.**

**(3) T-40 requires ABSOLUTE GIT EXECUTABLE RESOLUTION, because admitting a
general `PATH` reopens an uncontrolled executable/filter surface.** Two
measurements carry this.

*First, PATH is not needed, and works today only by accident of this host:*

```
  bare argv[0]='git', parent PATH = a dir with NO git    -> rc=0 git version 2.43.0
  bare argv[0]='git', parent PATH = '' (empty string)    -> rc=0 git version 2.43.0
  absolute argv[0]='/usr/bin/git', child env has NO PATH -> rc=0 git version 2.43.0
  git inside os.defpath ('/bin:/usr/bin')? True
```

Bare-`git` invocation survives an absent `PATH` only because CPython's
`execvp` falls back to `os.confstr("CS_PATH")` and git happens to live inside
`os.defpath` on this host. That is a **host property, not a guarantee**. The fix
is to resolve the binary to an absolute path once at start-up — **not** to admit
`PATH` so that git can find itself.

*Second, admitting `PATH` is what buys the attacker leg A.* The cost of
"just add PATH so `git` resolves" is measured: it is a working filter-driver
execution with attacker-chosen content, at `rc=0`, on a permitted row.

### AN HONEST BOUNDARY — what dropping `PATH` does NOT close

**Leg D, MEASURED:** child env is the allowlist with **no `PATH`**, but the
worker-controlled repository config names the smudge program by an **absolute
path**:

```
      repo cfg   : filter.z18.smudge = '/tmp/z18bin.ebp4u3j5/z18filter'
      PATH       : '(ABSENT)'
      -> rc=0  filter_EXECUTED=True  f.txt='HOSTILE_SMUDGE_RAN'
```

Removing `PATH` closes **bare-name** program resolution. It does **not** close
the filter-driver surface as such: git resolves the smudge command through
`/bin/sh`, and an absolute path needs no `PATH`. Under the threat model stated
in Z17's own probe — *"the worker controls repository CONFIG"* — legs D and E
are both reachable.

**Do not read leg C as "the filter surface is closed."** Read it as: *the
environment allowlist closes the inherited-environment route to it.* The
absolute-path route (D) and the displaced-argv route (E) are closed by other
mechanisms, or not at all. **Whether the design's repository-config sealing
closes leg D is NOT TESTED by this lane** — this probe deliberately grants the
worker config control in order to arm the positive control, so it cannot also
measure the seal that would remove it. That is a question for the lane that
owns the config seal, and it is flagged here rather than assumed away.

---

## F7-2 — the multi-pack-index is at `objects/pack/`, not `objects/info/`

Probe `exp9_pack_layout.py`, output `exp9_pack_layout.stdout.txt`.

### The location

```
  COMMAND: git multi-pack-index write
    $ git multi-pack-index write
      rc=0
    objects/info/multi-pack-index      exists = False   <- the SPECIFICATION's claim
    objects/pack/multi-pack-index      exists = True   <- MEASURED
    MEASURED LOCATION: objects/pack/multi-pack-index  mode=0664 size=1504 B
```

**MEASURED: on git 2.43.0 the multi-pack-index is written to
`objects/pack/multi-pack-index`.** The specification's `objects/info/` placement
is wrong. Three independent cross-checks, all in the transcript:

```
  CROSS-CHECK, git's own answer (git rev-parse --git-path):
      .git/objects/pack/multi-pack-index
  CROSS-CHECK, the file's own magic header:
      first 12 bytes = b'MIDX\x01\x01\x04\x00\x00\x00\x00\x01'   (MIDX signature is b'MIDX')
  CROSS-CHECK, git reads it back:
      verify rc=0 out=''
```

After the write, `objects/info/` contains exactly `['packs']` — no
`multi-pack-index` and no `multi-pack-index-*.bitmap`. The MIDX **bitmap** is
also in `objects/pack/`:
`multi-pack-index-c2bff688cb7afe1e4342a6e95bb23cee5d068329.bitmap`.

The confusion is understandable and worth naming in the design: the **commit
graph** *is* under `objects/info/` (`objects/info/commit-graph`,
`objects/info/commit-graphs/**`). The **multi-pack index is not.** They are
adjacent facts with different paths.

The detector is armed: `_exists()` first probes a path that must not exist and
aborts the run if it reports present.

### `objects/pack/**` inventory — every class, with the command that produced it

`exp9_pack_layout.py` builds a repository under `mktemp -d` and produces each
class deliberately. The roll-up is **cumulative across the whole run, not
final-state** — a later `git repack --cruft -a -d` deletes the pack bitmap an
earlier `git repack -a -d -b` created, so a final-state roll-up reports
`*.bitmap NOT OBSERVED` and is wrong. This probe's first draft did exactly that;
the bug is fixed and the trap is recorded in the source so it is not
reintroduced.

| Class | Status | Command that produced it |
|---|---|---|
| `*.pack` | **MEASURED — OBSERVED** | `git repack -a -d` |
| `*.idx` | **MEASURED — OBSERVED** | `git repack -a -d` |
| `*.rev` | **MEASURED — OBSERVED** | `git repack -a -d` (written by default on 2.43.0 — no `pack.writeReverseIndex` needed) |
| `*.bitmap` | **MEASURED — OBSERVED** | `git repack -a -d -b` |
| `*.mtimes` | **MEASURED — OBSERVED** | `git repack --cruft --cruft-expiration=never -a -d` (needs an unreachable object to hold) |
| `*.keep` | **MEASURED — OBSERVED** | `git pack-objects --revs --stdout` piped to `git index-pack --stdin --keep=<reason> --fix-thin` |
| `*.promisor` | **MEASURED — OBSERVED** | `git clone --no-local --filter=blob:none file://<src> <dst>` (source needs `uploadpack.allowFilter=true`) |
| `multi-pack-index` | **MEASURED — OBSERVED** | `git multi-pack-index write` |
| `multi-pack-index-*.bitmap` | **MEASURED — OBSERVED** | `git multi-pack-index write --bitmap` |

Classes observed but not on the wanted list: **(none)** — the enumeration was
complete for this probe's command set.

Observed modes and representative sizes are in the transcript. Two are worth
carrying into the design because they are not uniform:

* `multi-pack-index` is **`0664`** while `pack-*.pack/.idx/.rev/.bitmap/.mtimes`
  are **`0444`**; `*.keep` and `*.promisor` are **`0600`**. `objects/pack/**` is
  **not** uniformly read-only.
* A `*.promisor` marker is **not always empty**: the two produced by one partial
  clone were **103 B** and **0 B**.

`objects/info/` in the same repository ends the run containing exactly `packs`
(160 B), created by `git repack -a -d` — attributed in the transcript by a
listing taken immediately before and after that command.

**Incidental but load-bearing** (`exp9_pack_layout.stdout.txt` lines 189–192).
The design elsewhere names `extensions.partialClone` as a partial-clone signal.
On git 2.43.0 a `--filter=blob:none` clone over `file://` **does not write it**:

```
       $ git config --get extensions.partialClone            rc=1 out=''   <- NOT SET
       $ git config --get remote.origin.promisor             rc=0 out='true'
       $ git config --get remote.origin.partialclonefilter   rc=0 out='blob:none'
       $ git config --get core.repositoryformatversion       rc=0 out='1'
```

The signals that **are** written are `core.repositoryformatversion=1`,
`remote.<name>.promisor`, `remote.<name>.partialclonefilter`, and
`objects/pack/*.promisor`. Any check that requires `extensions.partialClone`
alone would miss this repository. **Verified twice** — once inside the probe and
once by a standalone `git clone` whose raw `.git/config` was read directly.

---

## F7-1 — a size-preserving byte alteration of a loose object is invisible to name+size

Probe `exp10_loose_object.py`, output `exp10_loose_object.stdout.txt`.

### The loose-object path shape, as git actually writes it

```
  --- object-format = sha1 (git reports: sha1) ---
    $ git hash-object -w --stdin   -> 9fc7f661153c7971be5eec436e495430e5e9f581
    files under .git/objects       : ['objects/9f/c7f661153c7971be5eec436e495430e5e9f581']
    fan-out dir  = '9f'   len=2
    object file  = 'c7f661153c7971be5eec436e495430e5e9f581'   len=38
    total hex    = 40   (oid length = 40)
    full path matches the SPEC regex 'objects/[0-9a-f]{2}/[0-9a-f]{38}' : True
    reassembled dir+file == oid    : True
```

**MEASURED: `objects/[0-9a-f]{2}/[0-9a-f]{38}` is exactly right — for a sha1
repository.** It is **not** right in general, and the probe measures the
counter-case rather than reasoning about it:

```
  --- object-format = sha256 (git reports: sha256) ---
    object file  = '6ffda477610b1d1b6cba645da7e7d9adca4998e4d2424ed631fadd6f4c47f8'   len=62
    file matches ^[0-9a-f]{38}$  : False
    full path matches the SPEC regex 'objects/[0-9a-f]{2}/[0-9a-f]{38}' : False
```

**MEASURED: a `--object-format=sha256` repository writes
`objects/[0-9a-f]{2}/[0-9a-f]{62}`,** which the specification's regex rejects.
The design should state the sha1 dependency rather than inherit it silently.

### The demonstration

Object: `9fc7f661153c7971be5eec436e495430e5e9f581`, file
`.git/objects/9f/c7f661153c7971be5eec436e495430e5e9f581`, **41 B**, mode `0444`.

**ARMING CONTROL FIRST.** A size-*changing* edit (one byte appended) must be
caught by the name+size capture, or its silence afterwards proves nothing:

```
    appended 1 byte -> size 41 -> 42
    NAME+SIZE capture now: [('c7f661153c7971be5eec436e495430e5e9f581', 42)]
    detector differs from golden: True   -> ARMED (control FIRED)
    git cat-file -p -> rc=0 stderr=''
```

Note the asymmetry, which is itself useful: the appended byte is caught by
**size** and **not** by git (`cat-file` returns `rc=0` — git ignores trailing
bytes after the deflate stream). The two detectors are complementary, and
neither subsumes the other.

**THE LEG UNDER TEST.** One byte in the middle of the deflate stream is XORed
with `0xFF` — one byte out, one byte in, length unchanged by construction — and
the mtime is then restored with `os.utime`, because an actor who can edit the
file can also restore its timestamp:

```
    byte offset 20 of 41: 0xc8 -> 0x37   (XOR 0xFF, length unchanged)

    path unchanged            : True  (.git/objects/9f/c7f661153c7971be5eec436e495430e5e9f581)
    size  41 -> 41          identical: True
    mode  0444 -> 0444      identical: True
    mtime_ns identical        : True
    sha256 2aafef804aeb8978... -> 57f4a00e90b1408d...   identical: False

    NAME+SIZE capture       : [('c7f661153c7971be5eec436e495430e5e9f581', 41)]
    NAME+SIZE detector      : SILENT — the alteration is INVISIBLE to it
    NAME+SIZE+MTIME detector: SILENT   (mtime was restored by the same actor that made the edit)
    SHA256-of-bytes detector: FIRED
```

**MEASURED — F7-1's premise HOLDS.** A capture recording only sorted names and
sizes for the loose fan-out is byte-identical before and after a real content
alteration. Adding mtime does not rescue it, because mtime is under the same
actor's control.

Git itself does notice, by a **different mechanism** — a loose object's *name is
its content hash* — and that distinction is exactly why the capture must not
lean on size:

```
      $ git cat-file -p 9fc7f661153c7971be5eec436e495430e5e9f581
        rc=128 stdout=''
        stderr='error: inflate: data stream error (incorrect data check)\nfatal: unable to stream 9fc7f661153c7971be5eec436e495430e5e9f581 to stdout'
      $ git fsck --no-progress
        rc=1
        error: inflate: data stream error (incorrect data check)
        error: corrupt loose object '9fc7f661153c7971be5eec436e495430e5e9f581'
        error: unable to unpack contents of .git/objects/9f/c7f661153c7971be5eec436e495430e5e9f581
        error: 9fc7f661153c7971be5eec436e495430e5e9f581: object corrupt or missing: .git/objects/9f/c7f661153c7971be5eec436e495430e5e9f581
      python zlib on the mutated bytes: zlib.error: Error -3 while decompressing data: incorrect data check
```

**A limit the design must state, not hide.** Because the path *is* the content
hash, a size-preserving edit of a loose object cannot substitute *valid
different content* at the same path — it can only **corrupt**. So the honest
claim is: *a name+size capture cannot see a size-preserving alteration of a
loose object; the resulting damage surfaces later as corruption at read time,
attributed to nobody.* **Substituting valid content at an unchanged loose path
is NOT ATTEMPTED here because it is arithmetically excluded** by the addressing
scheme, not because it was hard to test.

### What this experiment could have detected but did not

* that git writes loose objects at some other shape (flat, or 3/37);
* that a size-preserving alteration *does* change the name or size, i.e. that
  name+size is sufficient after all;
* that the name+size detector is simply broken — refuted by the arming leg
  before its silence was read as a result.

---

## Roll-up

| Claim | Label | Evidence |
|---|---|---|
| Z17's `exp8_path.py` positive control is dead; it exits `0` anyway | **MEASURED** | `exp8_ORIGINAL_dead_control.stdout.txt`, `exit-codes.txt` |
| A hostile `PATH` makes an in-tree `.gitattributes` smudge driver execute on `worktree add` and change checked-out content | **MEASURED** | `exp8b` leg A |
| The same, with a measured-absolute-path helper (pass-through) | **MEASURED** | `exp8b` leg A2 |
| The final child environment (allowlist, no `PATH`) + absolute git prevents it: no marker, safe content, `rc=0` | **MEASURED** | `exp8b` leg C |
| The environment allowlist does **not** close displaced argv `git -c` injection — **ZI-71 remains required** | **MEASURED** | `exp8b` leg E |
| Dropping `PATH` does **not** close an **absolute-path** smudge program | **MEASURED** | `exp8b` leg D |
| Whether the repository-config seal closes leg D | **NOT TESTED** | out of this lane's scope; this probe grants config control to arm its control |
| Bare `git` resolves without `PATH` only via `os.defpath` — a host property, hence **T-40** | **MEASURED** | `exp8b` §3 |
| Reproducing revision 8's claimed corrected run from revision 8's artefacts | **NOT ATTEMPTED** | no probe or output was committed to re-run |
| `multi-pack-index` lives at `objects/pack/multi-pack-index` on git 2.43.0, **not** `objects/info/` | **MEASURED** | `exp9` §3 |
| `multi-pack-index-*.bitmap` also lives in `objects/pack/` | **MEASURED** | `exp9` §4 |
| All nine `objects/pack/**` classes, each with its producing command | **MEASURED** | `exp9` §9 roll-up |
| `objects/pack/**` modes are **not** uniform (`0664`/`0444`/`0600`) | **MEASURED** | `exp9` listings |
| `extensions.partialClone` is not written by a 2.43.0 `--filter` clone over `file://` | **MEASURED** | `exp9` §8 |
| Loose path shape is `objects/[0-9a-f]{2}/[0-9a-f]{38}` for sha1 | **MEASURED** | `exp10` §1 |
| The same regex is wrong for a sha256 repository (`{62}` tail) | **MEASURED** | `exp10` §1 |
| A size-preserving loose-object alteration is invisible to a name+size (and name+size+mtime) capture, and visible to a content hash | **MEASURED** | `exp10` §2 |
| Substituting *valid different content* at an unchanged loose path | **NOT ATTEMPTED** | arithmetically excluded — the path is the content hash |

Nothing in this lane failed to fire. Every positive control fired on its first
recorded run; the one defect found in this lane's own work — a final-state
roll-up that under-reported `*.bitmap` — is fixed in `exp9_pack_layout.py` and
documented in its source rather than quietly corrected.
