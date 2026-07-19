"""polar-flow-server - Self-hosted health analytics server for Polar devices."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("polar-flow-server")
except PackageNotFoundError:  # running from a source checkout without an install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
