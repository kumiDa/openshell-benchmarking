sed -i 's/^    n = len(values)$/    values = sorted(values)\n    n = len(values)/' stats.py
