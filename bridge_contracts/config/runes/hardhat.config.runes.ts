import {task} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";
import {jsonAction} from '../base';

const PREFIX = 'runes-'

task(`${PREFIX}deploy-regtest`)
    .addOptionalParam("runeName", "Rune name")
    .addOptionalParam("runeSymbol", "Rune symbol")
    .addOptionalParam("owner", "Owner address")
    .setAction(jsonAction(async ({runeName, runeSymbol, owner}, hre) => {
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

        if (runeName) {
            if (!runeSymbol) {
                runeSymbol = runeName.charAt(0);

            }
            console.log(`Registering rune ${runeName} with symbol ${runeSymbol}`);
            const tx = await bridge.registerRune(
                runeName,
                runeSymbol
            );
            console.log('tx hash:', tx.hash, 'waiting for tx...');
            await tx.wait();
        }

        // temporarily set node1 as owner
        if (!owner) {
            console.log('Owner not given, using default owner');
            owner = '0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a';
        }
        if (owner) {
            console.log(`Setting owner to ${owner}`);
            const tx = await bridge.transferOwnership(owner);
            console.log('tx hash:', tx.hash, 'waiting for tx...');
            await tx.wait();
        }

        return {
            addresses: {
                RuneBridge: bridge.target
            }
        }
    }));

task(`${PREFIX}deploy-testnet`)
    .setAction(jsonAction(async ({}, hre) => {
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

        return {
            addresses: {
                RuneBridge: bridge.target
            }
        }
    }));

task(`${PREFIX}register-rune`)
    .addParam("bridgeAddress", "RuneBridge contract address")
    .addParam("runeName", "Rune name")
    .addParam("runeSymbol", "Rune symbol")
    .setAction(jsonAction(async ({runeName, runeSymbol, bridgeAddress}, hre) => {
        const ethers = hre.ethers;

        const bridge = await ethers.getContractAt("RuneBridge", bridgeAddress);

        console.log(`Registering rune ${runeName} with symbol ${runeSymbol}`);
        const tx = await bridge.registerRune(
            runeName,
            runeSymbol
        );
        console.log('tx hash:', tx.hash, 'waiting for tx...');
        await tx.wait();

        return {
            success: true,
        }
    }));


task(`${PREFIX}check-token-balances`)
    .addParam('bridge', 'Rune Bridge Address')
    .addParam('user', 'User address')
    .setAction(jsonAction(async ({bridge, user}, hre) => {
        const ethers = hre.ethers;
        const bridgeContract = await ethers.getContractAt("RuneBridge", bridge);
        const tokenAddresses = await bridgeContract.listTokens();
        const userBalancesByToken: Record<string, bigint> = {};
        console.log("Balances of user %s", user);
        for (const tokenAddress of tokenAddresses) {
            const token = await ethers.getContractAt("RuneSideToken", tokenAddress);
            const symbol = await token.symbol();
            const name = await token.name();
            const decimals = await token.decimals();

            const balanceWei = await token.balanceOf(user);
            const balance = ethers.formatUnits(balanceWei, decimals);

            const totalSupplyWei = await token.totalSupply();
            const totalSupply = ethers.formatUnits(totalSupplyWei, decimals);

            console.log(`${name}: ${balance} ${symbol} (Total supply: ${totalSupply} ${symbol})`);
            userBalancesByToken[tokenAddress] = balanceWei;
        }
        return userBalancesByToken;
    }));
