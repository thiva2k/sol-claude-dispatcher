#!/usr/bin/env python3
"""PROBE 2b - acceptance is not correctness. ACTUALLY apply each
dispatcher-composed patch and verify the file lands at the byte-exact path with
byte-exact content. Isolates git's trailing-TAB deviation for spaced names."""
import os, subprocess, tempfile

def sh(a, cwd=None, inp=None): return subprocess.run(a, cwd=cwd, input=inp, capture_output=True)

def cquote(pb):
    out = bytearray(); need = False
    for b in pb:
        if b == 0x22: out += b'\\"'; need=True
        elif b == 0x5c: out += b'\\\\'; need=True
        elif b == 0x0a: out += b'\\n'; need=True
        elif b == 0x09: out += b'\\t'; need=True
        elif b < 0x20 or b >= 0x80: out += b'\\%03o' % b; need=True
        else: out.append(b)
    return b'"'+bytes(out)+b'"' if need else pb

def hp(pre, pb):
    q = cquote(pb)
    return b'"'+pre+q[1:-1]+b'"' if q.startswith(b'"') else pre+q

def compose_new(pb, content, mode=b'100644', tab=False):
    a, b_ = hp(b'a/', pb), hp(b'b/', pb)
    t = b'\t' if tab else b''
    o = bytearray()
    o += b'diff --git '+a+b' '+b_+b'\n'
    o += b'new file mode '+mode+b'\n'
    if content == b'': return bytes(o)
    o += b'--- /dev/null\n'
    o += b'+++ '+b_+t+b'\n'
    lines = content.split(b'\n'); trail = content.endswith(b'\n')
    if trail: lines = lines[:-1]
    n = len(lines)
    o += (b'@@ -0,0 +1 @@\n' if n == 1 else b'@@ -0,0 +1,%d @@\n' % n)
    for i, l in enumerate(lines):
        o += b'+'+l+b'\n'
        if i == n-1 and not trail: o += b'\\ No newline at end of file\n'
    return bytes(o)

CAFE='café.txt'.encode(); NL=b'new\nline.txt'; TAB=b'tab\there.txt'
CASES=[('UTF-8 text', b'utf8.txt', 'héllo wörld\nsecond ✓\n'.encode(), b'100644'),
       ('empty file', b'empty.txt', b'', b'100644'),
       ('no-final-newline', b'nonl.txt', b'alpha\nbeta', b'100644'),
       ('filename with spaces', b'with space.txt', b'spaced\n', b'100644'),
       ('non-ASCII name cafe.txt', CAFE, b'cafe\n', b'100644'),
       ('newline in filename', NL, b'nl\n', b'100644'),
       ('tab in filename', TAB, b'tb\n', b'100644'),
       ('exec mode', b'run2.sh', b'#!/bin/sh\n', b'100755')]

root = tempfile.mkdtemp(prefix='z5real-'); print("ROOT=%s"%root)
print("git: %s\n"%sh(['git','--version']).stdout.decode().strip())
print("%-26s %-8s %-8s %-9s %-9s %s" % ("case","chk(no tab)","chk(tab)","applied","path OK","content OK"))
print("-"*92)
for label, pb, content, mode in CASES:
    row=[]
    for tab in (False, True):
        d=os.path.join(root, ("t" if tab else "n")+label.replace(' ','_').replace('/','_')[:20])
        os.makedirs(d, exist_ok=True); sh(['git','init','-q','-b','main',d])
        sh(['git','config','user.email','a@b'],cwd=d); sh(['git','config','user.name','a'],cwd=d)
        open(os.path.join(d,'seed.txt'),'wb').write(b'seed\n')
        sh(['git','add','seed.txt'],cwd=d); sh(['git','commit','-qm','s'],cwd=d)
        p = compose_new(pb, content, mode, tab=tab)
        chk = sh(['git','apply','--check','-'],cwd=d,inp=p)
        app = sh(['git','apply','-'],cwd=d,inp=p)
        # byte-exact path check: list the working tree, raw bytes
        got = sh(['find','.','-mindepth','1','-not','-path','./.git*','-type','f','-print0'],cwd=d).stdout
        names = [x[2:] for x in got.split(b'\x00') if x]
        pathok = (pb in names) if content!=b'' else ('N/A(no hunk)' if pb not in names else True)
        conok='?'
        if pb in names:
            fp=os.path.join(d.encode(), pb)
            conok = (open(fp,'rb').read()==content)
        row.append((chk.returncode, app.returncode, pathok, conok, chk.stderr.decode('utf-8','replace').strip()))
    (c0,a0,p0,k0,e0),(c1,a1,p1,k1,e1)=row
    print("%-26s %-11s %-8s %-9s %-9s %s" % (label, c0, c1, a0, p0, k0))
    if e0: print("      no-tab stderr: %s" % e0.replace('\n',' | '))
    if e1: print("      tab   stderr: %s" % e1.replace('\n',' | '))

print("\n=== the deviation, shown byte-exactly for 'with space.txt' ===")
d=os.path.join(root,'dev'); os.makedirs(d,exist_ok=True); sh(['git','init','-q','-b','main',d])
sh(['git','config','user.email','a@b'],cwd=d); sh(['git','config','user.name','a'],cwd=d)
open(os.path.join(d,'seed.txt'),'wb').write(b'seed\n'); sh(['git','add','seed.txt'],cwd=d); sh(['git','commit','-qm','s'],cwd=d)
open(os.path.join(d,'with space.txt'),'wb').write(b'spaced\n'); sh(['git','add','-N','--','with space.txt'],cwd=d)
gp=sh(['git','diff'],cwd=d).stdout
print("GIT'S OWN:"); print(repr(gp))
print("DISPATCHER (no tab):"); print(repr(compose_new(b'with space.txt', b'spaced\n')))
print("DISPATCHER (tab):"); print(repr(compose_new(b'with space.txt', b'spaced\n', tab=True)))

print("\n=== does a MISSING tab let git truncate the path at the space? ===")
for tab in (False,True):
    d2=os.path.join(root,'tr%d'%tab); os.makedirs(d2,exist_ok=True); sh(['git','init','-q','-b','main',d2])
    sh(['git','config','user.email','a@b'],cwd=d2); sh(['git','config','user.name','a'],cwd=d2)
    open(os.path.join(d2,'seed.txt'),'wb').write(b'seed\n'); sh(['git','add','seed.txt'],cwd=d2); sh(['git','commit','-qm','s'],cwd=d2)
    p=compose_new(b'with space.txt', b'spaced\n', tab=tab)
    r=sh(['git','apply','-v','-'],cwd=d2,inp=p)
    got=sh(['find','.','-mindepth','1','-not','-path','./.git*','-type','f'],cwd=d2).stdout.decode()
    print("  tab=%s applyrc=%s files=%s" % (tab, r.returncode, sorted(got.split())))
print("\nROOT kept at: %s"%root)
