#!/bin/bash

NODE_NAME=$BRIDGE_HOSTNAME

# Create node server key and certificate signing request (CSR)
openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 -out server.csr -keyout server-key.pem -subj "/C=FI/L=Oulu/O=Interjektio Oy/CN=${NODE_NAME}" -addext "subjectAltName = DNS:${NODE_NAME}" -addext "extendedKeyUsage = serverAuth"

# Sign the node server CSR with the CA certificate
openssl x509 -req -in server.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out server-cert.pem -days 365

# Create node client key and certificate signing request (CSR)
openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 -out client.csr -keyout client-key.pem -subj "/C=FI/L=Oulu/O=Interjektio Oy/CN=${NODE_NAME}" -addext "subjectAltName = DNS:${NODE_NAME}" -addext "extendedKeyUsage = clientAuth"

# Sign the node client CSR with the CA certificate
openssl x509 -req -in client.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out client-cert.pem -days 365

chmod 600 *.pem
