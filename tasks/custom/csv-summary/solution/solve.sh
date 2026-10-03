python3 -c "
import csv, json
t = {}
for r in csv.DictReader(open('sales.csv')):
    t[r['region']] = t.get(r['region'], 0) + int(r['units']) * float(r['unit_price'])
json.dump({k: round(v, 2) for k, v in t.items()}, open('summary.json', 'w'))
"
