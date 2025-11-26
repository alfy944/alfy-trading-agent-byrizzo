import os
import subprocess
import sys

TARGET_ENV_VAR = "RAILWAY_START_TARGET"
DEFAULT_TARGET = "main"


def main() -> int:
    target = os.getenv(TARGET_ENV_VAR, DEFAULT_TARGET)
    script = f"{target}.py"

    if not os.path.exists(script):
        sys.stderr.write(
            f"Error: target script '{script}' not found. Set {TARGET_ENV_VAR} to a valid module name without .py.\n"
        )
        return 1

    cmd = [sys.executable, script]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
