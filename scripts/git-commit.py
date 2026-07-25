import subprocess
from datetime import datetime

today_date = datetime.now().strftime("%Y-%m-%d")

commands = [
    (["git", "add", "."], True),
    (["git", "commit", "-m", f"Updated logs and trades {today_date}"], False),
    (["git", "push", "origin", "main"], True),
]

for command, stop_on_failure in commands:
    print(f"\n>>> {' '.join(command)}")

    result = subprocess.run(command)

    if result.returncode != 0:
        print(f"Command exited with {result.returncode}")

        if stop_on_failure:
            raise SystemExit(result.returncode)

print("\nDone!")
