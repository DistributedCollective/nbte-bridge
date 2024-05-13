#!/usr/bin/env python

import os
import socket
import subprocess

node_name = os.environ.get("BRIDGE_HOSTNAME", None)
node_ip = os.environ.get("BRIDGE_NODE_IP", None)

alt_name_node = f"DNS:{node_name}" if node_name else None
alt_name_ip = f"IP:{node_ip}" if node_ip else None

all_alt_names = [alt_name_node, alt_name_ip]

assert any(all_alt_names), "At least one of BRIDGE_HOSTNAME or BRIDGE_NODE_IP must be set"

san = "subjectAltName=" + ",".join([alt for alt in all_alt_names if alt])

# Create node server key and certificate signing request (CSR)
subprocess.run(
    f'openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 -out server.csr -keyout server-key.pem -subj "/O=Sovryn/CN={socket.gethostname()}" -addext "{san}" -addext extendedKeyUsage=serverAuth',
    check=True,
    shell=True,
)

# Sign the node server key with the CA
subprocess.run(
    "openssl x509 -req -in server.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out server-cert.pem -days 365 -copy_extensions copyall",
    check=True,
    shell=True,
)

# Create node client key and certificate signing request (CSR)
subprocess.run(
    f'openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 -out client.csr -keyout client-key.pem -subj "/O=Sovryn/CN={socket.gethostname()}" -addext "{san}" -addext extendedKeyUsage=clientAuth',
    check=True,
    shell=True,
)

# Sign the node client CSR with the CA certificate
subprocess.run(
    "openssl x509 -req -in client.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out client-cert.pem -days 365 -copy_extensions=copyall",
    check=True,
    shell=True,
)

subprocess.run("chmod 600 ./*.pem", check=True, shell=True)
