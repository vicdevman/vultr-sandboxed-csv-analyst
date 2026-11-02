"""All settings come from .env so switching OpenRouter -> Vultr is a config change, not a code change."""
import os

from dotenv import load_dotenv

load_dotenv()

INFERENCE_BASE_URL = os.environ.get("INFERENCE_BASE_URL", "")
INFERENCE_API_KEY = os.environ.get("INFERENCE_API_KEY", "")
MODEL = os.environ.get("MODEL", "")

SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "csv-analyst-sandbox:latest")
SANDBOX_RUNTIME = os.environ.get("SANDBOX_RUNTIME", "runc")
SANDBOX_TIMEOUT_SECONDS = int(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "20"))
SANDBOX_MEMORY = os.environ.get("SANDBOX_MEMORY", "512m")
SANDBOX_CPUS = os.environ.get("SANDBOX_CPUS", "1")
SANDBOX_PIDS_LIMIT = os.environ.get("SANDBOX_PIDS_LIMIT", "128")
MAX_REPAIR_ATTEMPTS = int(os.environ.get("MAX_REPAIR_ATTEMPTS", "3"))
