import {task, types} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";
import {jsonAction} from '../base';
import {ethers, upgrades} from 'hardhat';
import {getAdminAddress, getImplementationAddress} from '@openzeppelin/upgrades-core';

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
        const { ethers, upgrades } = hre;

        const RuneBridge = await ethers.getContractFactory("RuneBridge");
        const bridge = await upgrades.deployProxy(
            RuneBridge,
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
        const implementationAddress = await getImplementationAddress(ethers.provider, bridge.target as any);
        console.log(`Implementation deployed to ${implementationAddress}`);
        const proxyAdminAddress = await getAdminAddress(ethers.provider, bridge.target as any);
        console.log(`ProxyAdmin deployed to ${proxyAdminAddress}`);

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

        console.log("Disabling fees by default");
        const tx = await bridge.setEvmToBtcTransferPolicy(
            "0x0000000000000000000000000000000000000000",
            ethers.parseEther('1000000000000'),
            0,
            0,
            0,
            0,
        );
        console.log('tx hash:', tx.hash, 'waiting for tx...');
        await tx.wait();

        return {
            addresses: {
                RuneBridge: bridge.target,
                RuneBridgeProxy: bridge.target,
                RuneBridgeImplementation: implementationAddress,
                ProxyAdmin: proxyAdminAddress,
            }
        }
    }));


task(`deploy-rune-bridge-behind-proxy`)
    .addParam('accessControl', 'NBTEBridgeAccessControl address')
    .addParam('addressValidator', 'BTCAddressValidator address')
    .setAction(jsonAction(async ({
        accessControl,
        addressValidator,
    }, hre) => {
        const { ethers, upgrades } = hre;

        const RuneBridge = await ethers.getContractFactory("RuneBridge");
        const bridge = await upgrades.deployProxy(
            RuneBridge,
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
        const implementationAddress = await getImplementationAddress(ethers.provider, bridge.target as any);
        console.log(`Implementation deployed to ${implementationAddress}`);
        const proxyAdminAddress = await getAdminAddress(ethers.provider, bridge.target as any);
        console.log(`ProxyAdmin deployed to ${proxyAdminAddress}`);

        return {
            address: bridge.target,
            proxyAddress: bridge.target,
            implementationAddress: implementationAddress,
            proxyAdminAddress: proxyAdminAddress,
        }
    }));


task(`upgrade-rune-bridge`)
    .addParam("bridgeAddress", "RuneBridge contract address")
    .addParam("action", "Action to perform, either validate or upgrade")
    .setAction(jsonAction(async ({
        bridgeAddress,
        action,
    }, hre) => {
        const { ethers, upgrades } = hre;

        const currentImplementation = await getImplementationAddress(ethers.provider, bridgeAddress);
        console.log(`Current implementation: ${currentImplementation}`);
        const currentProxyAdmin = await getAdminAddress(ethers.provider, bridgeAddress);
        console.log(`CurrentProxyAdmin: ${currentProxyAdmin}`);

        const RuneBridge = await ethers.getContractFactory("RuneBridge");
        if (action === 'upgrade') {
            console.log("Upgrading");
            await upgrades.upgradeProxy(
                bridgeAddress,
                RuneBridge,
            );
        } else if (action === 'validate') {
            console.log("Validating upgrade");
            await upgrades.validateUpgrade(
                bridgeAddress,
                RuneBridge,
            );
            console.log("All good?");
            return {
                success: true,
            }
        } else {
            throw new Error(`Unknown action: ${action}`);
        }

        const newImplementationAddress = await getImplementationAddress(ethers.provider, bridgeAddress as any);
        console.log(`New implementation deployed to ${newImplementationAddress}`);

        return {
            success: true,
            newImplementationAddress,
        }
    }));


// TODO: temporary task, don't need it
task(`${PREFIX}test-access-control`)
    .addParam("bridgeAddress", "RuneBridge contract address")
    .setAction(async ({
        bridgeAddress,
    }, hre) => {
        const { ethers, upgrades } = hre;

        const runeBridge = await ethers.getContractAt("RuneBridge", bridgeAddress);

        const accessControlAddress = await runeBridge.accessControl();
        console.log(`Access control address: ${accessControlAddress}`);
        const accessControl = await ethers.getContractAt("NBTEBridgeAccessControl", accessControlAddress);

        const addr = "0x0000000000000000000000000000000000000000";
        console.log("Checking from access control");
        console.log(await accessControl.isFederator(addr));
        console.log("Checking from rune bridge control");
        console.log(await runeBridge.isFederator(addr));
    });


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


task(`${PREFIX}set-access-control`)
    .addParam("bridgeAddress", "RuneBridge contract address")
    .addParam("newAccessControl", "RuneBridge contract address")
    .setAction(jsonAction(async ({
        bridgeAddress,
        newAccessControl
    }, hre) => {
        const ethers = hre.ethers;

        const bridge = await ethers.getContractAt("RuneBridge", bridgeAddress);
        const tx = await bridge.setAccessControl(newAccessControl);
        console.log('tx hash:', tx.hash, 'waiting for tx...');
        await tx.wait();

        return {
            success: true,
        }
    }));


task(`${PREFIX}set-paused`)
    .addParam("bridgeAddress", "RuneBridge contract address")
    .addParam("paused", "RuneBridge contract address", undefined, types.boolean)
    .setAction(jsonAction(async ({
        bridgeAddress,
        paused
    }, hre) => {
        const ethers = hre.ethers;

        console.log(paused ? "Pausing" : "Unpausing" + " Rune bridge at " + bridgeAddress);
        const bridge = await ethers.getContractAt("RuneBridge", bridgeAddress);
        let tx;
        if (paused) {
            console.log("Pausing");
            tx = await bridge.pause();
        } else {
            console.log("Unpausing");
            tx = await bridge.unpause();
        }
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
