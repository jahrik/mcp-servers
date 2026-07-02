import os
import time

import jwt


def get_jwt() -> str:
    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")

    if not app_id or not private_key:
        raise RuntimeError(
            "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY environment variables must be set."
        )

    # Secrets managers and env-var injection commonly flatten a multi-line PEM into a
    # single line with literal `\n` escapes rather than real newlines.
    if "\\n" in private_key and "\n" not in private_key:
        private_key = private_key.replace("\\n", "\n")

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")
