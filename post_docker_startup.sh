#!/bin/bash
set -e
echo "Mining initial block"
docker-compose exec backend1 bitcoin-cli -datadir=/home/bitcoin/.bitcoin -regtest generatetoaddress 1 bcrt1qtxysk2megp39dnpw9va32huk5fesrlvutl0zdpc29asar4hfkrlqs2kzv5
sleep 2
ALICE_ADDR=$(
    docker-compose exec -u lnd alice /opt/lnd/lncli -n regtest newaddress p2tr | jq -r .address
)
echo "Generating 101 blocks to Alice: $ALICE_ADDR"
docker-compose exec backend1 bitcoin-cli -datadir=/home/bitcoin/.bitcoin -regtest generatetoaddress 101 $ALICE_ADDR

BOB_ADDR=$(
    docker-compose exec -u lnd bob /opt/lnd/lncli -n regtest newaddress p2tr | jq -r .address
)
echo "Generating 101 blocks to Bob: $BOB_ADDR"
docker-compose exec backend1 bitcoin-cli -datadir=/home/bitcoin/.bitcoin -regtest generatetoaddress 101 $BOB_ADDR

echo "All done!"
