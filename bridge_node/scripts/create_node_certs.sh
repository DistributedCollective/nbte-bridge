#!/bin/bash

NODE_NAME=$BRIDGE_HOSTNAME
NODE_IP=$BRIDGE_NODE_IP

SAN="subjectAltName="

# If node name exists, add to SAN
if [ -n "${NODE_NAME}" ]; then
  SAN="${SAN}DNS:${NODE_NAME}"
fi

# If node IP exists, add to SAN
if [ -n "${NODE_IP}" ]; then
  SAN="${SAN},IP:${NODE_IP}"
fi

# Create node server key and certificate signing request (CSR)
openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 -out server.csr -keyout server-key.pem -subj "/O=Sovryn/CN=$(hostname)" -addext "${SAN}" -addext "extendedKeyUsage = serverAuth"

# Sign the node server CSR with the CA certificate
openssl x509 -req -in server.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out server-cert.pem -days 365 -copy_extensions=copyall

# Create node client key and certificate signing request (CSR)
openssl req -new -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-256 -out client.csr -keyout client-key.pem -subj "/O=Sovryn/CN=$(hostname)" -addext "${SAN}" -addext "extendedKeyUsage = clientAuth"

# Sign the node client CSR with the CA certificate
openssl x509 -req -in client.csr -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out client-cert.pem -days 365 -copy_extensions=copyall

chmod 600 *.pem
