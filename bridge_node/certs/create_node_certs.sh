#!/bin/bash

NODE_NAME=$1

# Create node server key and certificate signing request (CSR)
openssl req -new -nodes -out ${NODE_NAME}-server.csr -keyout ${NODE_NAME}-server-key.pem -subj "/C=FI/L=Oulu/O=Interjektio Oy/CN=${NODE_NAME}" -addext "subjectAltName = DNS:${NODE_NAME}" -addext "extendedKeyUsage = serverAuth"

# Sign the node server CSR with the CA certificate
openssl x509 -req -in ${NODE_NAME}-server.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out ${NODE_NAME}-server-cert.pem -days 365

# Create node client key and certificate signing request (CSR)
openssl req -new -nodes -out ${NODE_NAME}-client.csr -keyout ${NODE_NAME}-client-key.pem -subj "/C=FI/L=Oulu/O=Interjektio Oy/CN=${NODE_NAME}" -addext "subjectAltName = DNS:${NODE_NAME}" -addext "extendedKeyUsage = clientAuth"

# Sign the node client CSR with the CA certificate
openssl x509 -req -in ${NODE_NAME}-client.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out ${NODE_NAME}-client-cert.pem -days 365
