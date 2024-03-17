#!/bin/sh
if [ "$INTEGRATION_TEST" = "1" ]
then
    # Launch integration test startup setup on the background
    # This is a legacy thing and not the cleanest. We should aim to get rid of it.
    echo "Running hardhat in legacy integration test mode (deploying everything)"
    (npx hardhat --network localhost wait-for-startup &&
    npx hardhat --network localhost deploy-regtest &&
    npx hardhat --network localhost free-money $USER_ADDRESS 10.0 &&
    npx hardhat --network localhost free-money $NODE1_ADDRESS 10.0 &&
    npx hardhat --network localhost free-money $NODE2_ADDRESS 10.0 &&
    npx hardhat --network localhost free-money $NODE3_ADDRESS 10.0 &&
    npx hardhat --network localhost set-mining-interval 10000)&
fi

# Launch hardhat node no matter if we're running in integration test mode or not
npx hardhat node --hostname 0.0.0.0
