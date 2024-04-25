#!/usr/bin/env python

import subprocess

subprocess.run(
    "openssl ecparam -name P-256 -genkey -noout -out ca-key.pem",
    shell=True,
    check=True,
)

subprocess.run(
    "openssl req -new -x509 -nodes -days 365000 -key ca-key.pem -out ca-cert.pem -subj /O=Sovryn/CN=ca",
    shell=True,
    check=True,
)

subprocess.run("chmod 600 ./*.pem", check=True, shell=True)
