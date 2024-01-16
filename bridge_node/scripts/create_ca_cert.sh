#!/bin/bash

# Create a CA certificate
openssl ecparam -name P-256 -genkey > ca-key.pem
openssl req -new -x509 -nodes -days 365000 \
   -key ca-key.pem \
   -out ca-cert.pem \
   -subj "/C=FI/L=Oulu/O=Interjektio Oy/CN=ca"

chmod 600 *.pem
