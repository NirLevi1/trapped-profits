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

LOGIC_VERSION = "2026.10.13-a"   # 13.10: סף 25% מדויק; "בסיס מהמאזן" לא לבדיקה ידנית
