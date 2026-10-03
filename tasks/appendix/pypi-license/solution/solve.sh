curl -fsS https://pypi.org/pypi/tabulate/0.9.0/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['license'])" > license.txt
