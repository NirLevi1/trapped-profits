"""22.10: בדיקה לאחור של אומדני מאזן הבוחן – חותכים שנה שלמה (יוני/אוגוסט/ספטמבר) ומשווים לשנה האמיתית.
הרצה: TP_REAL=<תיקייה> python tools/tb_backtest.py"""
import sys,glob,os,copy,json,collections
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trapped_profits.importers import parse_trial_balance
from trapped_profits.models import ClientInput
from trapped_profits.engine import _tb_table
S=os.environ.get('TP_REAL', '.')  # תיקייה עם clients/<לקוח>/רווח והפסד <שנה>.csv (ו-batch4.json) – נתונים אמיתיים, לא במאגר
cases=[('re','2025',None),('re_1','2025',None),('re_6','2025',None),('re_3','2025','2024'),('re_3','2024',None)]
CUTS=[int(x) for x in (sys.argv[1] if len(sys.argv)>1 else '6,8,9').split(',')]
bym=collections.defaultdict(list); summ=[]
for c,y,py in cases:
    full=parse_trial_balance(glob.glob(f'{S}/clients/{c}/רווח והפסד {y}*')[0])['fields']['tb_rows']
    prev=parse_trial_balance(glob.glob(f'{S}/clients/{c}/רווח והפסד {py}*')[0])['fields']['tb_rows'] if py else []
    for cut in CUTS:
        tb=copy.deepcopy(full)
        for r in tb: r['months']=[ (v if i<cut else 0) for i,v in enumerate(r['months'])]
        ci=ClientInput.from_dict({'structure':{'name':'x','tax_year':int(y)},'tb_rows':tb,'tb_rows_prev_year':prev,'data_through_month':cut})
        _,_,mt,_=_tb_table(ci)
        act={r['id']:abs(sum(float(v or 0) for v in r['months'])) for r in full}
        A=collections.Counter(); E=collections.Counter()
        for r in mt['rows']:
            a=act[r['id']]; e=r['total']; k='rev' if r['kind']=='revenue' else ('exp' if r['kind']=='expense' else 'oth')
            A[k]+=a; E[k]+=e
            if a>20000 or e>20000:
                bym[r['method'].split(' ')[0]].append((c,y,cut,r['name'],a,e))
        prof_a=A['rev']-A['exp']; prof_e=E['rev']-E['exp']
        summ.append((c,y,cut,A['rev'],E['rev'],A['exp'],E['exp'],prof_a,prof_e, (prof_a/A['rev'] if A['rev'] else 0),(prof_e/E['rev'] if E['rev'] else 0)))
print("לקוח שנה עד | הכנסות בפועל/אומדן (סטייה) | הוצאות בפועל/אומדן (סטייה) | רווחיות בפועל/אומדן")
for c,y,cut,ar,er,ae,ee,pa,pe,ra,re_ in summ:
    print(f"{c:5}{y} עד {cut:2} | {ar:>10,.0f} {er:>10,.0f} ({(er-ar)/ar:+.0%}) | {ae:>10,.0f} {ee:>10,.0f} ({(ee-ae)/ae:+.0%}) | {ra:.1%} → {re_:.1%}")
print()
for meth,lst in bym.items():
    errs=[(e-a)/a for *_,a,e in lst if a>0]
    big=sorted(lst,key=lambda x: -abs((x[5]-x[4])/(x[4] or 1)))[:6]
    import statistics
    print(f"== {meth}: {len(lst)} שורות, סטייה חציונית {statistics.median([abs(x) for x in errs]):.0%}, ממוצעת {statistics.mean(errs):+.0%}")
    for c,y,cut,n,a,e in big: print(f"     {c} {y} עד {cut}: {n}: בפועל {a:,.0f} אומדן {e:,.0f} ({(e-a)/(a or 1):+.0%})")
