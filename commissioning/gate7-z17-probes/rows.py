#!/usr/bin/env python3
"""Z17 — the eight permitted rows, runnable under an arbitrary child environment.

No shell anywhere. git is invoked by ABSOLUTE PATH so that PATH's necessity is a
measurement rather than a precondition of the harness.
"""
from __future__ import annotations
import os, subprocess, tempfile, shutil, sys, json

GIT = "/usr/bin/git"

PIN_ARGV = [
    "-c", "core.commitGraph=false",
    "-c", "core.multiPackIndex=false",
    "-c", "core.fsmonitor=false",
    "-c", "core.attributesFile=/dev/null",
    "-c", "core.quotePath=false",
    "--no-pager",
]

def pin_block(hooksdir: str) -> list[str]:
    return ["-c", f"core.hooksPath={hooksdir}"] + PIN_ARGV


def run(argv, cwd, env, stdin=None, timeout=60):
    return subprocess.run([GIT, *argv], cwd=cwd, env=env, input=stdin,
                          capture_output=True, text=True, timeout=timeout)


class Fixture:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="z17root.")
        self.ext = tempfile.mkdtemp(prefix="z17ext.")
        self.hooks = tempfile.mkdtemp(prefix="z17hooks.")
        e = dict(os.environ); e["GIT_CONFIG_NOSYSTEM"] = "1"
        def g(*a, **kw):
            r = subprocess.run([GIT, *a], cwd=kw.pop("cwd", self.root), env=e,
                               capture_output=True, text=True, **kw)
            if r.returncode != 0:
                raise RuntimeError(f"fixture {a}: {r.returncode} {r.stderr}")
            return r.stdout.strip()
        g("init", "-q", "-b", "main", ".")
        g("config", "user.email", "z17@probe.invalid")
        g("config", "user.name", "Z17")
        open(f"{self.root}/a.txt", "w").write("one\n")
        os.mkdir(f"{self.root}/sub"); open(f"{self.root}/sub/b.txt", "w").write("two\n")
        g("add", "-A"); g("commit", "-q", "-m", "c1")
        open(f"{self.root}/c.txt", "w").write("three\n")
        g("add", "-A"); g("commit", "-q", "-m", "c2")
        open(f"{self.root}/a.txt", "a").write("four\n")
        g("add", "-A"); g("commit", "-q", "-m", "c3")
        self.base = g("rev-parse", "HEAD")
        self.trueroot = g("rev-list", "--max-parents=0", "HEAD")
        tree = g("rev-parse", "HEAD^{tree}")
        self.decoy = g("commit-tree", "-m", "decoy", tree)
        self.wt = f"{self.ext}/task-wt"
        g("worktree", "add", "--quiet", "--detach", self.wt, self.base)
        self.blob = g("rev-parse", "HEAD:a.txt")
        # golden outputs, captured under the ambient (full) environment + pins
        self.golden = {}
        full = self.child_env(dict(os.environ))
        for name, _ in ROWS:
            self.golden[name] = self.row(name, full, record=True)

    def child_env(self, base):
        e = dict(base)
        for k in list(e):
            if k.startswith("GIT_"):
                e.pop(k)
        e["GIT_NO_LAZY_FETCH"] = "1"
        e["GIT_NO_REPLACE_OBJECTS"] = "1"
        e["GIT_CONFIG_NOSYSTEM"] = "1"
        e["GIT_CONFIG_GLOBAL"] = "/dev/null"
        e["GIT_TERMINAL_PROMPT"] = "0"
        e["GIT_OPTIONAL_LOCKS"] = "0"
        return e

    def row(self, name, env, record=False):
        pb = pin_block(self.hooks)
        if name == "G1":
            r = run(pb + ["rev-parse", "--verify", "--end-of-options",
                          f"{self.base}^{{commit}}"], self.root, env)
        elif name == "G2":
            r = run(pb + ["ls-tree", "-r", "-z", self.base], self.root, env)
        elif name == "G3":
            r = run(pb + ["worktree", "list", "--porcelain"], self.root, env)
        elif name == "G4":
            d = tempfile.mkdtemp(prefix="z17add."); shutil.rmtree(d)
            r = run(pb + ["worktree", "add", "--quiet", "--detach", d, self.base],
                    self.root, env, timeout=300)
            ok = os.path.isdir(d)
            if os.path.isdir(d):
                subprocess.run([GIT, "worktree", "remove", "--force", d],
                               cwd=self.root, env=self.child_env(dict(os.environ)),
                               capture_output=True)
            return {"rc": r.returncode, "out": f"created={ok}", "err": r.stderr[:300]}
        elif name == "G8":
            r = run(pb + ["cat-file", "--batch"], self.root, env,
                    stdin=f"{self.base}\n{self.blob}\n")
        elif name == "G9":
            r = run(pb + ["rev-list", "--objects", "--missing=print", "HEAD"],
                    self.root, env)
        elif name == "G10a":
            r = run(pb + ["rev-parse", "--absolute-git-dir"], self.root, env)
        elif name == "G10b":
            r = run(pb + ["rev-parse", "--git-common-dir"], self.root, env)
        elif name == "RESUME":
            # resume row G1': base re-verification, cwd = the TASK WORKTREE
            r = run(pb + ["rev-parse", "--verify", "--end-of-options",
                          f"{self.base}^{{commit}}"], self.wt, env)
        else:
            raise KeyError(name)
        return {"rc": r.returncode, "out": r.stdout, "err": r.stderr[:300]}

    def cleanup(self):
        for d in (self.root, self.ext, self.hooks):
            shutil.rmtree(d, ignore_errors=True)


ROWS = [("G1", "rev-parse --verify"), ("G2", "ls-tree -r -z"),
        ("G3", "worktree list --porcelain"), ("G4", "worktree add --detach"),
        ("G8", "cat-file --batch"), ("G9", "rev-list --objects --missing=print"),
        ("G10a", "rev-parse --absolute-git-dir"),
        ("G10b", "rev-parse --git-common-dir"),
        ("RESUME", "rev-parse --verify (cwd=task worktree)")]


def compare(fx, name, env):
    """Returns (ok, detail). ok means rc==0 AND output identical to golden."""
    got = fx.row(name, env)
    want = fx.golden[name]
    if got["rc"] != 0:
        return False, f"rc={got['rc']} err={got['err'].strip()[:180]!r}"
    if got["out"] != want["out"]:
        return False, f"rc=0 but OUTPUT DIFFERS ({len(got['out'])} vs {len(want['out'])} bytes)"
    return True, "ok"
