import {task} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";

const PREFIX = 'runes-'

task(`${PREFIX}deploy-regtest`)
    .setAction(async ({}, hre) => {
        const ethers = hre.ethers;

        const bridge = await ethers.deployContract(
            "RuneBridge",
            [
            ],
            {}
        );
        await bridge.waitForDeployment();
        console.log(
            `RuneBridge deployed to ${bridge.target}`
        );

        // temporarily set node1 as owner
        const owner = '0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a';
        if (owner) {
            console.log(`Setting owner to ${owner}`);
            const tx = await bridge.transferOwnership(owner);
            console.log('tx hash:', tx.hash, 'waiting for tx...');
            await tx.wait();
        }
    });


task(`${PREFIX}-check-token-balances`)
    .addParam('bridge', 'Rune Bridge Address')
    .addParam('user', 'User address')
    .setAction(async ({bridge, user}, hre) => {
        const ethers = hre.ethers;
        const bridgeContract = await ethers.getContractAt("RuneBridge", bridge);
        const tokenAddresses = await bridgeContract.listTokens();
        console.log("Balances of user %s", user);
        for (const tokenAddress of tokenAddresses) {
            const token = await ethers.getContractAt("RuneSideToken", tokenAddress);
            const symbol = await token.symbol();
            const name = await token.name();
            const decimals = await token.decimals();

            const balanceWei = await token.balanceOf(user);
            const balance = ethers.formatUnits(balanceWei, decimals);
            console.log(`${balance} ${symbol} (${name})`);
        }
    });
