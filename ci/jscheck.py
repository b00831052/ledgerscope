"""Pre-push gate: every inline <script> in index.html, terminal.html and ALL fund pages must parse (node --check).
Identical scripts are checked once (fund pages share the same code), so the full site checks in seconds."""
import re, subprocess, sys, os, glob, tempfile, hashlib, shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = next((p for p in [shutil.which("node"), os.path.expanduser("~/.local/node/bin/node"),
                         "/opt/homebrew/bin/node", "/usr/local/bin/node"] if p and os.path.exists(p)), None)
if not NODE:
    print("jscheck: FAIL (node not found)"); sys.exit(1)

files = [os.path.join(HERE, "index.html"), os.path.join(HERE, "terminal.html")] + \
        sorted(glob.glob(os.path.join(HERE, "fund", "**", "index.html"), recursive=True))
seen, bad = {}, 0
for f in files:
    src = open(f, encoding="utf-8").read()
    for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S):
        js = m.group(1)
        h = hashlib.sha1(js.encode()).hexdigest()
        if h not in seen:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
                tf.write(js); p = tf.name
            r = subprocess.run([NODE, "--check", p], capture_output=True, text=True); os.unlink(p)
            seen[h] = r.returncode == 0
            if r.returncode:
                print("JS ERROR in", os.path.relpath(f, HERE), "|", (r.stderr.strip().splitlines() or [""])[-1])
        if not seen[h]: bad += 1
print("jscheck:", "FAIL" if bad else "OK", f"({len(files)} files, {len(seen)} unique scripts, node={NODE})")
sys.exit(1 if bad else 0)
