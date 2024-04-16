import {task, types} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";
import {jsonAction} from '../base';

const PREFIX = 'runes-'

task(`${PREFIX}deploy-regtest`)
    .addParam('accessControl', 'NBTEBridgeAccessControl address')
    .addParam('addressValidator', 'BTCAddressValidator address')
    .addOptionalParam("runeName", "Rune name to register")
    .addOptionalParam("runeSymbol", "Rune symbol to register")
    .setAction(jsonAction(async ({
        accessControl,
        addressValidator,
        runeName,
        runeSymbol,
    }, hre) => {
        const ethers = hre.ethers;

        const bridge = await ethers.deployContract(
            "RuneBridge",
            [
                accessControl,
                addressValidator,
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

        return {
            addresses: {
                RuneBridge: bridge.target
            }
        }
    }));


task(`deploy-rune-bridge`)
    .addParam('accessControl', 'NBTEBridgeAccessControl address')
    .addParam('addressValidator', 'BTCAddressValidator address')
    .setAction(jsonAction(async ({
        accessControl,
        addressValidator,
    }, hre) => {
        const ethers = hre.ethers;

        const bridge = await ethers.deployContract(
            "RuneBridge",
            [
                accessControl,
                addressValidator,
            ],
            {}
        );
        await bridge.waitForDeployment();
        console.log(
            `RuneBridge deployed to ${bridge.target}`
        );

        return {
            address: bridge.target,
        }
    }));

task(`${PREFIX}register-rune`)
    .addParam("bridgeAddress", "RuneBridge contract address")
    .addParam("runeNumber", "Rune number")
    .addParam("runeDivisibility", "Rune number", undefined, types.int)
    .addParam("runeName", "Rune name")
    .addParam("runeSymbol", "Rune symbol")
    .setAction(jsonAction(async ({
        runeNumber,
        runeDivisibility,
        runeName,
        runeSymbol,
        bridgeAddress
    }, hre) => {
        const ethers = hre.ethers;
        runeNumber = BigInt(runeNumber);

        const bridge = await ethers.getContractAt("RuneBridge", bridgeAddress);

        console.log(`Registering rune ${runeName} with symbol ${runeSymbol}`);
        const tx = await bridge.registerRune(
            runeName,
            runeSymbol,
            runeNumber,
            runeDivisibility
        );
        console.log('tx hash:', tx.hash, 'waiting for tx...');
        await tx.wait();

        return {
            success: true,
        }
    }));


task(`${PREFIX}set-evm-to-btc-transfer-policy`)
    .addParam("bridgeAddress", "RuneBridge contract address")
    .addParam("token", "Token address")
    .addOptionalParam("maxTokenAmount")
    .addOptionalParam("minTokenAmount")
    .addOptionalParam("flatFeeBaseCurrency")
    .addOptionalParam("flatFeeTokens")
    .addOptionalParam("dynamicFeeTokens")
    .setAction(jsonAction(async ({
        bridgeAddress,
        token,
        maxTokenAmount,
        minTokenAmount,
        flatFeeBaseCurrency,
        flatFeeTokens,
        dynamicFeeTokens
    }, hre) => {
        const ethers = hre.ethers;

        const bridge = await ethers.getContractAt("RuneBridge", bridgeAddress);

        const oldPolicy = await bridge.getEvmToBtcTransferPolicy(token);
        console.log('Old policy:', oldPolicy);

        let newPolicy = {
            maxTokenAmount: oldPolicy.maxTokenAmount,
            minTokenAmount: oldPolicy.minTokenAmount,
            flatFeeBaseCurrency: oldPolicy.flatFeeBaseCurrency,
            flatFeeTokens: oldPolicy.flatFeeTokens,
            dynamicFeeTokens: oldPolicy.dynamicFeeTokens
        };
        if (maxTokenAmount) {
            newPolicy.maxTokenAmount = BigInt(maxTokenAmount);
        }
        if (minTokenAmount) {
            newPolicy.minTokenAmount = BigInt(minTokenAmount);
        }
        if (flatFeeBaseCurrency) {
            newPolicy.flatFeeBaseCurrency = BigInt(flatFeeBaseCurrency);
        }
        if (flatFeeTokens) {
            newPolicy.flatFeeTokens = BigInt(flatFeeTokens);
        }
        if (dynamicFeeTokens) {
            newPolicy.dynamicFeeTokens = BigInt(dynamicFeeTokens);
        }

        console.log(`Setting EVM to BTC transfer policy for token ${token}`);
        const tx = await bridge.setEvmToBtcTransferPolicy(
            token,
            newPolicy.maxTokenAmount,
            newPolicy.minTokenAmount,
            newPolicy.flatFeeBaseCurrency,
            newPolicy.flatFeeTokens,
            newPolicy.dynamicFeeTokens
        );
        console.log('tx hash:', tx.hash, 'waiting for tx...');
        await tx.wait();

        return {
            success: true,
        }
    }));


task(`${PREFIX}list-tokens`)
    .addParam("bridgeAddress", "RuneBridge contract address")
    .setAction(jsonAction(async ({
        bridgeAddress
    }, hre) => {
        const ethers = hre.ethers;

        const bridge = await ethers.getContractAt("RuneBridge", bridgeAddress);
        const tokens = await bridge.listTokens();

        return {
            tokens,
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
            const token = await ethers.getContractAt("RuneToken", tokenAddress);
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
