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

APP_VERSION = "1.10"               # גרסת התוכנה שמוצגת למשתמש
LOGIC_VERSION = "2026.10.17-a"   # 17.10: סטטוס 62א עם פטור 750 אלף; קריאת דוחות (עלות, "-", שם, ריכוזיות)
