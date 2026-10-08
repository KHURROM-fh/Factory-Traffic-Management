from pathlib import Path
import environ

# BASE_DIR points to backend/ root
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()

# Read .env file from BASE_DIR
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file)
