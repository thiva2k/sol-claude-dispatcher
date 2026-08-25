#!/usr/bin/env python3
"""PROBE 2 - do DISPATCHER-COMPOSED patches survive `git apply --check`?

Composes patches exactly as GATE7-DESIGN.md specifies (dispatcher-native,
`--- /dev/null` -> `+++ b/<path>`, `@@` ranges, real content, C-quoted headers
for hostile names) and validates each against a real `git apply --check` in a
throwaway repo. Also compares byte-exactly with git's own rendering.
"""
import os, subprocess, tempfile, shutil, sys

def sh(args, cwd=None, inp=None):
    return subprocess.run(args, cwd=cwd, input=inp, capture_output=True)

def cquote(pb: bytes) -> bytes:
    """git's C-quoting, as used in patch headers when the path needs it."""
    need = False
    out = bytearray()
    for b in pb:
        if b == 0x22: out += b'\\"'; need = True
        elif b == 0x5c: out += b'\\\\'; need = True
        elif b == 0x0a: out += b'\\n'; need = True
        elif b == 0x09: out += b'\\t'; need = True
        elif b < 0x20 or b >= 0x80: out += b'\\%03o' % b; need = True
        else: out.append(b)
    return b'"' + bytes(out) + b'"' if need else pb

def hdr_path(prefix: bytes, pb: bytes, quote_nonascii=True) -> bytes:
    q = cquote(pb) if quote_nonascii else pb
    if q.startswith(b'"'):
        # git quotes the WHOLE "a/path" token, prefix inside the quotes
        inner = q[1:-1]
        return b'"' + prefix + inner + b'"'
    return prefix + q

def compose_new_file(path_bytes: bytes, content: bytes, mode=b'100644',
                     quote_nonascii=True, empty_style='no-hunk') -> bytes:
    a = hdr_path(b'a/', path_bytes, quote_nonascii)
    b = hdr_path(b'b/', path_bytes, quote_nonascii)
    out = bytearray()
    out += b'diff --git ' + a + b' ' + b + b'\n'
    out += b'new file mode ' + mode + b'\n'
    if content == b'' and empty_style == 'no-hunk':
        return bytes(out)
    out += b'--- /dev/null\n'
    out += b'+++ ' + b + b'\n'
    lines = content.split(b'\n')
    trailing_nl = content.endswith(b'\n')
    if trailing_nl:
        lines = lines[:-1]
    n = len(lines)
    if content == b'':
        out += b'@@ -0,0 +0,0 @@\n'
        return bytes(out)
    out += b'@@ -0,0 +1,%d @@\n' % n if n != 1 else b'@@ -0,0 +1 @@\n'
    for i, ln in enumerate(lines):
        out += b'+' + ln + b'\n'
        if i == n - 1 and not trailing_nl:
            out += b'\\ No newline at end of file\n'
    return bytes(out)

def compose_modify(path_bytes: bytes, old: bytes, new: bytes,
                   quote_nonascii=True) -> bytes:
    """Single whole-file hunk (the simplest correct unified diff)."""
    a = hdr_path(b'a/', path_bytes, quote_nonascii)
    b = hdr_path(b'b/', path_bytes, quote_nonascii)
    def split(c):
        L = c.split(b'\n'); t = c.endswith(b'\n')
        if t: L = L[:-1]
        return L, t
    ol, ot = split(old); nl, nt = split(new)
    out = bytearray()
    out += b'diff --git ' + a + b' ' + b + b'\n'
    out += b'--- ' + hdr_path(b'a/', path_bytes, quote_nonascii) + b'\n'
    out += b'+++ ' + b + b'\n'
    def rng(k): return b'1' if k == 1 else b'1,%d' % k
    out += b'@@ -' + rng(len(ol)) + b' +' + rng(len(nl)) + b' @@\n'
    for i, x in enumerate(ol):
        out += b'-' + x + b'\n'
        if i == len(ol) - 1 and not ot: out += b'\\ No newline at end of file\n'
    for i, x in enumerate(nl):
        out += b'+' + x + b'\n'
        if i == len(nl) - 1 and not nt: out += b'\\ No newline at end of file\n'
    return bytes(out)

CAFE = 'caf\u00e9.txt'.encode()
CASES = [
    # label, path bytes, content bytes, kind
    ('UTF-8 text (ascii name)',      b'utf8.txt',        'h\u00e9llo w\u00f6rld\nsecond \u2713 line\n'.encode(), 'new'),
    ('empty file',                   b'empty.txt',       b'',                              'new'),
    ('no-final-newline',             b'nonl.txt',        b'alpha\nbeta',                   'new'),
    ('filename with spaces',         b'with space.txt',  b'spaced content\n',              'new'),
    ('non-ASCII filename cafe.txt',  CAFE,               b'cafe content\n',                'new'),
    ('single-line no-final-newline', b'one.txt',         b'only',                          'new'),
    ('exec mode new file',           b'run2.sh',         b'#!/bin/sh\necho hi\n',          'new755'),
]
MODS = [
    ('MODIFY utf8 (ascii name)',     b'm_utf8.txt', 'a\u00e9\nb\n'.encode(), 'a\u00e9\nB-CHANGED\n'.encode()),
    ('MODIFY -> no-final-newline',   b'm_nonl.txt', b'a\nb\n',               b'a\nb-changed'),
    ('MODIFY from no-final-newline', b'm_nonl2.txt', b'a\nb',                b'a\nb-changed\n'),
    ('MODIFY spaces name',           b'm with space.txt', b'x\n',            b'y\n'),
    ('MODIFY cafe name',             'm_caf\u00e9.txt'.encode(), b'x\n',     b'y\n'),
]

root = tempfile.mkdtemp(prefix='z5apply-')
print("ROOT=%s" % root)
print("git: %s" % sh(['git','--version']).stdout.decode().strip())

def fresh_repo(name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    sh(['git','init','-q','-b','main', d])
    sh(['git','config','user.email','a@b'], cwd=d); sh(['git','config','user.name','a'], cwd=d)
    return d

def apply_check(repo, patch, extra=()):
    r = sh(['git','apply','--check','-v', *extra, '-'], cwd=repo, inp=patch)
    return r.returncode, (r.stderr + r.stdout).decode('utf-8','replace').strip()

results = []
print("\n" + "="*100)
print("PART 1 - NEW FILE patches (/dev/null -> b/<path>), dispatcher-composed")
print("="*100)
for label, pb, content, kind in CASES:
    mode = b'100755' if kind == 'new755' else b'100644'
    repo = fresh_repo('n_' + label.replace(' ','_').replace('/','_')[:24])
    # baseline commit so `git apply` has an index/HEAD
    open(os.path.join(repo,'seed.txt'),'wb').write(b'seed\n')
    sh(['git','add','seed.txt'], cwd=repo); sh(['git','commit','-qm','seed'], cwd=repo)
    patch = compose_new_file(pb, content, mode)
    rc, msg = apply_check(repo, patch)
    # also try the quoting-off variant for non-ascii
    rc2 = msg2 = None
    if any(b >= 0x80 for b in pb):
        p2 = compose_new_file(pb, content, mode, quote_nonascii=False)
        rc2, msg2 = apply_check(repo, p2)
    # git's own rendering of the same change, for byte comparison
    fp = os.path.join(repo, pb.decode('utf-8','surrogateescape'))
    os.makedirs(os.path.dirname(fp), exist_ok=True) if os.path.dirname(fp)!=repo else None
    with open(fp.encode('utf-8','surrogateescape'), 'wb') as f: f.write(content)
    if kind == 'new755': os.chmod(fp.encode('utf-8','surrogateescape'), 0o755)
    sh(['git','add','-N','--', pb.decode('utf-8','surrogateescape')], cwd=repo)
    gitpatch = sh(['git','diff','--','.'], cwd=repo).stdout
    same = (gitpatch == patch)
    results.append((label, rc, rc2, same))
    print("\n--- %s ---" % label)
    print("  composed patch (%d bytes):" % len(patch))
    for l in patch.decode('utf-8','replace').splitlines(): print("    | %s" % l)
    print("  git apply --check  rc=%s  %s" % (rc, "ACCEPTED" if rc==0 else "REJECTED: "+msg))
    if rc2 is not None:
        print("  [unquoted non-ASCII header variant] rc=%s %s" % (rc2, "ACCEPTED" if rc2==0 else "REJECTED: "+msg2))
    print("  byte-identical to git's own `git diff` rendering? %s" % ("YES" if same else "NO"))
    if not same:
        print("  git's own rendering:")
        for l in gitpatch.decode('utf-8','replace').splitlines(): print("    > %s" % l)

print("\n" + "="*100)
print("PART 2 - MODIFY patches (a/<path> -> b/<path>)")
print("="*100)
for label, pb, old, new in MODS:
    repo = fresh_repo('m_' + label.replace(' ','_')[:24])
    fp = os.path.join(repo, pb.decode('utf-8','surrogateescape'))
    with open(fp.encode('utf-8','surrogateescape'),'wb') as f: f.write(old)
    sh(['git','add','-A'], cwd=repo); sh(['git','commit','-qm','base'], cwd=repo)
    patch = compose_modify(pb, old, new)
    rc, msg = apply_check(repo, patch)
    with open(fp.encode('utf-8','surrogateescape'),'wb') as f: f.write(new)
    gitpatch = sh(['git','diff'], cwd=repo).stdout
    # strip index line from git's version for structural comparison
    gp_nolines = b'\n'.join(l for l in gitpatch.split(b'\n') if not l.startswith(b'index '))
    same = (gp_nolines == patch)
    results.append((label, rc, None, same))
    print("\n--- %s ---" % label)
    for l in patch.decode('utf-8','replace').splitlines(): print("    | %s" % l)
    print("  git apply --check  rc=%s  %s" % (rc, "ACCEPTED" if rc==0 else "REJECTED: "+msg))
    print("  identical to git's rendering (index line removed)? %s" % ("YES" if same else "NO"))
    if not same:
        for l in gitpatch.decode('utf-8','replace').splitlines(): print("    > %s" % l)

print("\n" + "="*100)
print("PART 3 - EMPTY FILE: which of the three plausible renderings does git accept?")
print("="*100)
for style, patch in [
    ('header only, no ---/+++ , no hunk (git\'s own form)',
     b'diff --git a/e1.txt b/e1.txt\nnew file mode 100644\n'),
    ('with ---/+++ and @@ -0,0 +0,0 @@',
     b'diff --git a/e2.txt b/e2.txt\nnew file mode 100644\n--- /dev/null\n+++ b/e2.txt\n@@ -0,0 +0,0 @@\n'),
    ('with ---/+++ and NO hunk',
     b'diff --git a/e3.txt b/e3.txt\nnew file mode 100644\n--- /dev/null\n+++ b/e3.txt\n'),
    ('header only WITHOUT new file mode',
     b'diff --git a/e4.txt b/e4.txt\n'),
]:
    repo = fresh_repo('e_%d' % (abs(hash(style)) % 10**8))
    open(os.path.join(repo,'seed.txt'),'wb').write(b'seed\n')
    sh(['git','add','seed.txt'], cwd=repo); sh(['git','commit','-qm','seed'], cwd=repo)
    rc, msg = apply_check(repo, patch)
    print("  %-52s rc=%s %s" % (style, rc, "ACCEPTED" if rc==0 else "REJECTED: "+msg.replace('\n',' | ')))

print("\n" + "="*100)
print("PART 4 - MULTI-SECTION patch, sections ordered by raw path bytes (as design specifies)")
print("="*100)
repo = fresh_repo('multi')
open(os.path.join(repo,'seed.txt'),'wb').write(b'seed\n')
sh(['git','add','seed.txt'], cwd=repo); sh(['git','commit','-qm','seed'], cwd=repo)
secs = []
for label, pb, content, kind in CASES:
    if content == b'':   # skip the header-only empty in the multi test body
        secs.append((pb, compose_new_file(pb, content, b'100644')))
    else:
        secs.append((pb, compose_new_file(pb, content, b'100755' if kind=='new755' else b'100644')))
secs.sort(key=lambda t: t[0])
whole = b''.join(s for _, s in secs)
rc, msg = apply_check(repo, whole)
print("  sections (raw-byte order): %s" % [p.decode('utf-8','replace') for p,_ in secs])
print("  whole-patch git apply --check rc=%s %s" % (rc, "ACCEPTED" if rc==0 else "REJECTED: "+msg.replace('\n',' | ')))
rc3, msg3 = apply_check(repo, whole, extra=('--check','--3way') if False else ())
r = sh(['git','apply','--stat','-'], cwd=repo, inp=whole)
print("  git apply --stat rc=%s:\n%s" % (r.returncode, '\n'.join('    '+l for l in r.stdout.decode('utf-8','replace').splitlines())))

print("\n" + "="*100)
print("SUMMARY  (label | apply --check rc | unquoted-variant rc | byte-identical to git)")
print("="*100)
for label, rc, rc2, same in results:
    print("  %-34s rc=%-3s alt=%-4s identical=%s" % (label, rc, rc2, same))
print("\nROOT kept at: %s" % root)
