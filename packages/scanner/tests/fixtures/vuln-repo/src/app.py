import subprocess
import yaml
import requests


def run(cmd, user_id, cur):
    subprocess.call(cmd, shell=True)
    cur.execute("SELECT * FROM users WHERE id = '%s'" % user_id)
    requests.get("https://example.com", verify=False)
    return yaml.load(open("c.yml"))


def unused():
    import os
    undefined_name_here
