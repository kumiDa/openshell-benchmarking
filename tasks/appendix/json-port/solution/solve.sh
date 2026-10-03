python3 -c "import json; c=json.load(open('config.json')); c['port']=8080; json.dump(c, open('config.json','w'), indent=2)"
