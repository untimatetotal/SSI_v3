import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("ENCRYPTION_KEY", "Jz2b0wq1N8x8k3c9mYq3x6k3sJ0b6u8w1a2b3c4d5e8=")
