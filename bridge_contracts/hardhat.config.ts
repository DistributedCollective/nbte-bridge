import { HardhatUserConfig } from "hardhat/config";
import {task, types} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";
import { jsonAction } from './config/base';
import './config/tap/hardhat.config.tap';
import './config/runes/hardhat.config.runes';

const TESTNET_DEPLOYER_PRIVATE_KEY = process.env.TESTNET_DEPLOYER_PRIVATE_KEY || '';
const MAINNET_DEPLOYER_PRIVATE_KEY = process.env.MAINNET_DEPLOYER_PRIVATE_KEY || '';

const config: HardhatUserConfig = {
    solidity: {
        compilers: [
            {
                version: "0.8.19"
            },
        ],
    },
    networks: {
        "docker": {
            url: "http://localhost:18545",
        },
        "rsk-testnet": {
            url: "https://testnet.sovryn.app/rpc",
            chainId: 31,
            accounts: TESTNET_DEPLOYER_PRIVATE_KEY ? [TESTNET_DEPLOYER_PRIVATE_KEY] : [],
        },
        "rsk-mainnet": {
            url: "https://mainnet.sovryn.app/rpc",
            chainId: 30,
            accounts: MAINNET_DEPLOYER_PRIVATE_KEY ? [MAINNET_DEPLOYER_PRIVATE_KEY] : [],
        },
    },
};


// ==========
// DEPLOYMENT
// ==========

task('deploy-access-control')
    .addOptionalParam('admins', 'Admin addresses, comma separated')
    .addOptionalParam('federators', 'Federator addresses, comma separated')
    .setAction(jsonAction(async ({ admins, federators }, hre) => {
        const ethers = hre.ethers;
        const accessControl = await ethers.deployContract(
            "NBTEBridgeAccessControl",
            [],
            {}
        );
        console.log("NBTEBridgeAccessControl deployed at %s", accessControl.target)
        await accessControl.waitForDeployment();
        if (admins) {
            for (const admin of admins.split(',')) {
                console.log("Adding admin %s", admin)
                const tx = await accessControl.addAdmin(admin);
                await tx.wait();
            }
        }
        if (federators) {
            for (const federator of federators.split(',')) {
                console.log("Adding federator %s", federator)
                const tx = await accessControl.addFederator(federator);
                await tx.wait();
            }
        }
        return {
            address: accessControl.target
        };
    }));

task('deploy-btc-address-validator')
    .addParam('accessControl', 'Access control address')
    .addParam('bech32Prefix', 'Bech32 prefix')
    .addParam('nonBech32Prefixes', 'Non-bech32 prefixes (comma separated)')
    .setAction(jsonAction(async ({ accessControl, bech32Prefix, nonBech32Prefixes }, hre) => {
        const ethers = hre.ethers;
        const deployment = await ethers.deployContract(
            "BTCAddressValidator",
            [accessControl, bech32Prefix, nonBech32Prefixes.split(',')],
            {}
        );
        console.log("BTCAddressValidator deployed at %s", deployment.target)
        await deployment.waitForDeployment();
        return {
            address: deployment.target
        };
    }));

task("deploy-regtest")
    .setAction(jsonAction(async ({}, hre) => {
        console.log("Deploying regtest");

        console.log("Deploying tap bridge");
        // TODO: use access control and btc address validator for tap bridge
        const tapBridgeResult = await hre.run("tap-deploy-regtest");

        const accessControlResult = await hre.run("deploy-access-control", {
            federators: '0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a,0x09dcD91DF9300a81a4b9C85FDd04345C3De58F48,0x0000000000000000000000000000000000000123',
            admins: '0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a',
        });
        const btcAddressValidatorResult = await hre.run("deploy-btc-address-validator", {
            accessControl: accessControlResult.address,
            bech32Prefix: 'bcrt1',
            nonBech32Prefixes: 'm',
        });

        console.log("Deploying rune bridge");
        const runesResult = await hre.run("runes-deploy-regtest", {
            accessControl: accessControlResult.address,
            addressValidator: btcAddressValidatorResult.address,
        });
        return {
            addresses: {
                'TapBridge': tapBridgeResult.addresses.TapBridge,
                'RuneBridge': runesResult.addresses.RuneBridge,
                NBTEBridgeAccessControl: accessControlResult.address,
                BTCAddressValidator: btcAddressValidatorResult.address,
            }
        }
    }));


// ============
// TEST HELPERS
// ============

task("deploy-testtoken")
    .addParam("supply", "Initial supply of the token", "0")
    .setAction(jsonAction(async (taskArgs, hre) => {
        const ethers = hre.ethers;
        const tokenSupply = ethers.parseUnits(taskArgs.supply, 18);
        const testToken = await ethers.deployContract(
            "TestToken",
            ["TestToken", "TT", tokenSupply],
            {}
        );
        await testToken.waitForDeployment();
        return {
            "address": testToken.target
        };
    }))


task("accounts", "Prints the list of accounts", async (args, hre) => {
    const accounts = await hre.ethers.getSigners();

    for (const account of accounts) {
        const balance = await hre.ethers.provider.getBalance(account.address);
        console.log(account.address, "balance:", hre.ethers.formatEther(balance));
    }
});

task("free-money", "Sends free money to address")
    .addPositionalParam("address", "Address to send free money to")
    .addPositionalParam("rbtcAmount", "RBTC amount to send", "1.0")
    .setAction(async ({ address, rbtcAmount }, hre) => {
        if(!address) {
            throw new Error("Provide address as first argument");
        }
        const rbtcAmountWei = hre.ethers.parseEther(rbtcAmount);
        console.log(`Sending ${rbtcAmount} rBTC (${rbtcAmountWei} wei) to ${address}`)

        const accounts = await hre.ethers.getSigners();

        const tx = await accounts[0].sendTransaction({
            to: address,
            value: rbtcAmountWei,
        })

        console.log('tx hash:', tx.hash, 'waiting for tx...');
        await tx.wait();
    });

task("wait-for-startup", "Wait for network startup")
    .addOptionalParam("maxWaitTime", "Maximum wait time in seconds")
    .setAction(async ({ maxWaitTime = 600 }, hre) => {
        console.log(`Waiting for connection to ${hre.network.name} (max ${maxWaitTime} seconds)`)
        const start = Date.now();
        const deadline = start + maxWaitTime * 1000;
        let lastError;
        while (true) {
            const timeLeftMs = deadline - Date.now();
            if (timeLeftMs < 0) {
                break;
            }

            try {
                await hre.network.provider.send('eth_chainId', []);
                console.log(`Connected to network ${hre.network.name}!`)
                return;
            } catch (e) {
                lastError = e;
                console.log(`Could not connect to network ${hre.network.name}, waiting... (${timeLeftMs/1000}s left)`);
                await sleep(5000);
            }
        }
        console.error(lastError);
        throw new Error("Could not connect to network");
    })

task("verify-started", "Check if started")
    .setAction(async ({}, hre) => {
        try {
            await hre.network.provider.send('eth_chainId', []);
            console.log(`Connected to network ${hre.network.name}!`)
            return;
        } catch (e) {
            console.log(`Could not connect to network ${hre.network.name}`);
            throw e;
        }
    })

task('set-mining-interval', "Set mining interval")
    .addPositionalParam('ms', 'Mining interval as milliseconds (0 for automine)', undefined, types.int)
    .setAction(jsonAction(async ({ ms }, hre) => {
        if (ms === 0) {
            console.log("Enabling automining");
            await hre.network.provider.send('evm_setIntervalMining', [0]);
            await hre.network.provider.send('evm_setAutomine', [true]);
            return {
                automine: true,
                miningIntervalMs: ms,
            }
        } else {
            console.log("Disabling automining and enabling interval mining with", ms, "ms");
            await hre.network.provider.send('evm_setAutomine', [false]);
            await hre.network.provider.send('evm_setIntervalMining', [ms]);
            return {
                automine: false,
                miningIntervalMs: ms,
            }
        }
    }));


// =================
// UTILITY FUNCTIONS
// =================

async function sleep(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// default export
export default config;
