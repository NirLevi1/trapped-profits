"""22.10: בדיקה לאחור של אומדני מאזן הבוחן – חותכים שנה שלמה (יוני/אוגוסט/ספטמבר) ומשווים לשנה האמיתית.
הרצה: TP_REAL=<תיקייה> python tools/tb_lawtest.py"""
import sys,glob,copy,json
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trapped_profits.importers import parse_trial_balance
from trapped_profits.models import ClientInput
from trapped_profits.engine import compute
S=os.environ.get('TP_REAL', '.')  # תיקייה עם clients/<לקוח>/רווח והפסד <שנה>.csv (ו-batch4.json) – נתונים אמיתיים, לא במאגר
B=json.load(open(S+'/batch4.json'))
cases=[('re','2025',None),('re_1','2025',None),('re_6','2025',None),('re_3','2025','2024'),('re_3','2024',None)]
errs=[]
for c,y,py in cases:
    full=parse_trial_balance(glob.glob(f'{S}/clients/{c}/רווח והפסד {y}*')[0])['fields']
    prev=parse_trial_balance(glob.glob(f'{S}/clients/{c}/רווח והפסד {py}*')[0])['fields']['tb_rows'] if py else []
    base=copy.deepcopy(B[c]['input']); base['structure']['tax_year']=int(y)
    base['structure']['last_closed_report_year']=int(y)-1
    def run(cut):
        inp=copy.deepcopy(base); tb=copy.deepcopy(full['tb_rows'])
        for r in tb: r['months']=[(v if i<cut else 0) for i,v in enumerate(r['months'])]
        inp['tb_rows']=tb; inp['tb_rows_prev_year']=prev; inp['data_through_month']=cut; inp['adjustments']=[]
        inp['tb_approved']={'by':'x','at':'2026','through_month':cut}
        res=compute(ClientInput.from_dict(inp))
        return res.s62a.governing_profitability, res.s62a.attributed_income
    pa,aa=run(12)
    line=f"{c} {y}: אמיתי {pa:.1%} (תיקון {aa:,.0f})"
    for cut in (6,8,9):
        p,a=run(cut); errs.append(abs(p-pa)); flip=(p>0.25)!=(pa>0.25)
        line+=f" | עד {cut}: {p:.1%}{' ⚠ הפך צד' if flip else ''}"
    print(line)
print(f"סטייה ממוצעת ברווחיות: {sum(errs)/len(errs):.1%}, הפיכות צד: ", )
