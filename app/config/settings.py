from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

META_VERIFY_TOKEN = os.getenv(
    "META_VERIFY_TOKEN"
)

META_ACCESS_TOKEN = os.getenv(
    "META_ACCESS_TOKEN"
)

META_PHONE_NUMBER_ID = os.getenv(
    "META_PHONE_NUMBER_ID"
)

META_APP_SECRET = os.getenv(
    "META_APP_SECRET"
)


# ---------------------------------------------------------------------------
# LLM / extraction configuration (centralized).
# Existing extraction providers still read these keys directly from the
# environment; these constants provide a single documented reference and
# consistent defaults for new code (e.g. material research).
# ---------------------------------------------------------------------------
EXTRACTION_PROVIDER = os.getenv("EXTRACTION_PROVIDER", "gemini").lower()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

# Operational config
ADMIN_WHATSAPP_NUMBER = os.getenv("ADMIN_WHATSAPP_NUMBER")
ERP_CONNECTOR = os.getenv("ERP_CONNECTOR", "noop")
REMINDER_SCHEDULER_ENABLED = os.getenv("REMINDER_SCHEDULER_ENABLED", "1") != "0"
WHATSAPP_RFQ_TEMPLATE = os.getenv("WHATSAPP_RFQ_TEMPLATE", "rfq_invitation")
