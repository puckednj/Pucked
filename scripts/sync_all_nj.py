import subprocess
import sys

SCRIPTS = [
    'scripts/collect_floydhall.py',
    'scripts/collect_mennen.py',
    'scripts/collect_codey.py',
    'scripts/collect_icehouse.py',
    'scripts/collect_skylands.py',
    'scripts/collect_icevault.py',
    'scripts/collect_bridgewater.py',
]

def main():
    python_exe = sys.executable
    for script in SCRIPTS:
        print(f"\n=== Running {script} ===")
        res = subprocess.run([python_exe, script])
        if res.returncode != 0:
            raise SystemExit(f"Failed while running {script}")
    print("\nAll 7 New Jersey rink collectors finished cleanly!")

if __name__ == '__main__':
    main()
