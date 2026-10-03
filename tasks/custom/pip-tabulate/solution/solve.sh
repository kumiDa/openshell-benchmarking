python3 -m pip install --user -q tabulate==0.9.0 && python3 -c "
import csv, tabulate
rows = list(csv.reader(open('inventory.csv')))
open('inventory.md', 'w').write(tabulate.tabulate(rows[1:], headers=rows[0], tablefmt='github') + '\n')
"
