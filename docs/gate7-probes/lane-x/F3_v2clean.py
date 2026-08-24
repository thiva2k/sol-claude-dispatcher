import subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/home/dev/sol-claude-dispatcher/src")
from sol_claude_dispatcher.git import collect_diff_evidence, check_scope
from sol_claude_dispatcher.models import ScopeSpec
def sh(c, cwd=None): return subprocess.run(c, cwd=cwd, shell=isinstance(c,str), capture_output=True, text=True)
root = Path(tempfile.mkdtemp()); p = root/"primary"; (p/"secrets").mkdir(parents=True)
sh(["git","init","-q","-b","main",str(p)]); sh("git config user.email p@x && git config user.name p", cwd=p)
(p/"secrets/.keep").write_text("k\n"); sh("git add -A && git commit -qm init", cwd=p)
base = sh(["git","rev-parse","HEAD"],cwd=p).stdout.strip()
wt = root/"wt"; sh(["git","worktree","add","--quiet","-b","t",str(wt),base], cwd=p)
# ONLY a non-ASCII forbidden file — the clean V-2 case
(wt/"secrets/café.txt").write_text("stolen\n")
ev = collect_diff_evidence(wt, base)
scope = ScopeSpec(allowed_paths=[], forbidden_paths=["secrets/**"])
sc = check_scope(ev.changed_paths, scope)
print("changed_paths:", ev.changed_paths)
print("forbidden_paths=['secrets/**'], allowed=[] (unrestricted otherwise)")
print("  valid  :", sc.valid, "  <-- V-2: TRUE means the forbidden write PASSED")
print("  forbidden:", sc.forbidden)
