from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional


class RouterAction(str, Enum):
    """Available routing actions"""
    DIRECT_ANSWER = "direct_answer"
    RAG_SEARCH = "rag_search"
    VISION_ANALYSIS = "vision_analysis"
    EXTERNAL_API = "external_api"
    MEMORY_LOOKUP = "memory_lookup"
    AGENTIC = "agentic"  # Complex tasks requiring multi-step reasoning and tool use


class RouterResult(BaseModel):
    """Router classification result"""
    action: RouterAction
    confidence: float = Field(ge=0.0, le=1.0)
    reason: Optional[str] = None


# Confidence thresholds
CONFIDENCE_THRESHOLD_HIGH = 0.8
CONFIDENCE_THRESHOLD_LOW = 0.5

# Default fallback action when confidence is too low
DEFAULT_FALLBACK_ACTION = RouterAction.RAG_SEARCH

# Keywords that strongly indicate specific actions
ACTION_KEYWORDS = {
    RouterAction.VISION_ANALYSIS: [
        "image", "picture", "photo", "chart", "graph", "diagram",
        "screenshot", "visual", "see", "look at", "shown", "display"
    ],
    RouterAction.RAG_SEARCH: [
        # English — document references
        "document", "pdf", "file", "uploaded", "attachment",
        "summarize", "extract", "search in", "find in",
        "sop", "company", "based on my", "according to my",
        "my files", "my documents", "knowledge base",
        "in the document", "from the document", "in my",
        "from my", "my sop", "company policy", "guidelines",
        "procedures", "manual", "handbook", "report",
        "regulation", "policy", "rule", "according to",
        # Indonesian — document / regulation queries
        "menurut",        # according to
        "berdasarkan",    # based on
        "sesuai",         # in accordance with
        "peraturan",      # regulation
        "aturan",         # rule
        "ketentuan",      # provision
        "kebijakan",      # policy
        "prosedur",       # procedure
        "tata cara",      # procedure / steps
        "panduan",        # guide / guidelines
        "regulasi",       # regulation
        "pedoman",        # guideline / manual
        "undang",         # law (part of "undang-undang")
        "pasal",          # article (of a regulation)
        "bab",            # chapter (of a document)
        "bank indonesia",
        "ojk",
        "dokumen",        # document
        "laporan",        # report
        "ringkasan",      # summary
        "rangkuman",      # summary
        "jelaskan",       # explain (often asks about doc content)
        "apa itu",        # what is (domain question)
        "bagaimana",      # how (procedure questions)
        "syarat",         # requirement / condition
        "kewajiban",      # obligation
        "mekanisme",      # mechanism
        "pasar uang",     # money market
        "pasar valuta",   # foreign exchange market
        "sro",            # self-regulatory organization
    ],
    RouterAction.EXTERNAL_API: [
        # Moved to AGENTIC - external API is not implemented
    ],
    RouterAction.MEMORY_LOOKUP: [
        "previous", "earlier", "before", "last time", "remember",
        "continue", "we discussed", "you said", "mentioned"
    ],
    RouterAction.AGENTIC: [
        # Web search triggers (English)
        "search", "latest", "news", "current", "today", "now",
        "price", "weather", "stock", "crypto", "bitcoin", "live",
        "search the web", "find on internet", "look up online",
        "look up", "find out", "what is the current",
        "exchange rate", "forex",
        # Web search triggers (Indonesian)
        "cari", "terbaru", "berita", "hari ini", "sekarang",
        "harga", "cuaca", "lihat web", "cari di internet",
        "cari online", "temukan", "cek", "update",
        "saat ini",       # right now / at this moment
        "terkini",        # latest / current
        "kurs",           # exchange rate
        "nilai tukar",    # exchange rate
        "rupiah",         # often paired with exchange rate queries
        "dolar",          # USD
        "euro",           # EUR
        "saham",          # stock
        "per hari ini",   # as of today
        "inflasi",        # inflation (real-time economic data)
        "bi rate",        # Bank Indonesia rate
        "suku bunga",     # interest rate (live data)
        # Research triggers
        "research", "investigate", "analyze and", "compare",
        "step by step", "plan", "complex", "calculate and explain",
        "help me with", "figure out", "multiple steps",
        "use tools", "search and summarize", "find and analyze"
    ],
}
