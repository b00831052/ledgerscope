"""Pre-push gate: every inline <script> in index.html and a sample of fund pages must parse (node --check)."""
import re, subprocess, sys, os, glob, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = [os.path.join(HERE, "index.html")] + sorted(glob.glob(os.path.join(HERE, "fund", "*", "index.html")))[:20] + [os.path.join(HERE, "fund", "index.html")]
bad = 0
for f in files:
    for i, s in enumerate(re.findall(r"<script>(.*?)</script>", open(f, encoding="utf-8").read(), re.S)):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf: tf.write(s); p = tf.name
        r = subprocess.run(["node", "--check", p], capture_output=True, text=True); os.unlink(p)
        if r.returncode: bad += 1; print("JS ERROR", f, "script", i, r.stderr.strip().splitlines()[-1] if r.stderr else "")
print("jscheck:", "FAIL" if bad else "OK", f"({len(files)} files)")
sys.exit(1 if bad else 0)
