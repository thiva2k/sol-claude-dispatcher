import subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/home/dev/sol-claude-dispatcher/src")
from sol_claude_dispatcher.git import collect_diff_evidence, check_scope
from sol_claude_dispatcher.models import ScopeSpec
def sh(c, cwd=None):
    return subprocess.run(c, cwd=cwd, shell=isinstance(c,str), capture_output=True, text=True)
root = Path(tempfile.mkdtemp()); p = root/"primary"; (p/"secrets").mkdir(parents=True); (p/"src").mkdir()
sh(["git","init","-q","-b","main",str(p)]); sh("git config user.email p@x && git config user.name p", cwd=p)
(p/"secrets/.keep").write_text("k\n"); (p/"src/a.txt").write_text("a\n")
sh("git add -A && git commit -qm init", cwd=p)
base = sh(["git","rev-parse","HEAD"],cwd=p).stdout.strip()
wt = root/"wt"; sh(["git","worktree","add","--quiet","-b","t",str(wt),base], cwd=p)
for name in ["café.txt", "naïve.key", "plain.txt"]:
    (wt/"secrets"/name).write_text("stolen\n")
ev = collect_diff_evidence(wt, base)
print("changed_paths:", ev.changed_paths)
for scope in [ScopeSpec(allowed_paths=[], forbidden_paths=["secrets/**"]),
              ScopeSpec(allowed_paths=["src/**"], forbidden_paths=["secrets/**"])]:
    sc = check_scope(ev.changed_paths, scope)
    print(f"\nscope allowed={scope.allowed_paths} forbidden={scope.forbidden_paths}")
    print("  valid       :", sc.valid)
    print("  forbidden   :", sc.forbidden)
    print("  out_of_scope:", sc.out_of_scope)
# now the -z variant
raw = subprocess.run(["git","-C",str(wt),"ls-files","--others","--exclude-standard","-z"],capture_output=True).stdout
paths = [x.decode() for x in raw.split(b"\0") if x]
print("\n-z decoded changed_paths:", paths)
sc = check_scope(paths, ScopeSpec(allowed_paths=[], forbidden_paths=["secrets/**"]))
print("  valid with -z:", sc.valid, "| forbidden:", sc.forbidden)
