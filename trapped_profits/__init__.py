"""מנוע חישוב – חוק הרווחים הכלואים (תיקון 277 לפקודה).

תרגום אחד-לאחד של קובץ האקסל "לוגיקה חישובים לניטור רווחים כלואים" (גרסת 28.9.2026).
כל פונקציה מציינת בהערה את התא באקסל שהיא מממשת, כדי שאפשר יהיה לאמת מולו.
"""

from .models import (
    CompanyStructure,
    RetainedEarningsInput,
    ShieldsInput,
    DistributionsInput,
    Section62AInput,
    Flags,
    ClientInput,
)
from .engine import compute, ClientResult

__all__ = [
    "CompanyStructure",
    "RetainedEarningsInput",
    "ShieldsInput",
    "DistributionsInput",
    "Section62AInput",
    "Flags",
    "ClientInput",
    "compute",
    "ClientResult",
]

APP_VERSION = "1.5"               # גרסת התוכנה שמוצגת למשתמש
LOGIC_VERSION = "2026.10.15-e"   # 15.10: תרחיש ג׳ – דוח סגור ישן בשנתיים, גלגול שנתיים
