import os
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("myvitals")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

# These are baked in at Docker build time (see Dockerfile ARGs / CI).
GIT_SHA: str = os.getenv("GIT_SHA", "unknown")
BUILD_TIME: str = os.getenv("BUILD_TIME", "unknown")


def info() -> dict[str, str]:
    return {"version": __version__, "git_sha": GIT_SHA, "build_time": BUILD_TIME}
