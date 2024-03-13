import { HardhatUserConfig } from "hardhat/config";
import {task, types} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";
import './config/tap/hardhat.config.tap';
import './config/runes/hardhat.config.runes';

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
    }
};


// ==========
// DEPLOYMENT
// ==========

task("deploy-regtest")
    .setAction(async ({}, hre) => {
        console.log("Deploying regtest");

        console.log("Deploying tap bridge");
        await hre.run("tap-deploy-regtest");

        console.log("Deploying rune bridge");
        await hre.run("runes-deploy-regtest");
    });



// ============
// TEST HELPERS
// ============

task("deploy-testtoken")
    .addParam("supply", "Initial supply of the token", "0")
    .setAction(async (taskArgs, hre) => {
        const ethers = hre.ethers;
        const tokenSupply = ethers.parseUnits(taskArgs.supply, 18);
        const testToken = await ethers.deployContract(
            "TestToken",
            ["TestToken", "TT", tokenSupply],
            {}
        );
        await testToken.waitForDeployment();
        console.log(JSON.stringify({"address": testToken.target}));
    })


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
    .setAction(async ({ ms }, hre) => {
        if (ms === 0) {
            console.log("Enabling automining");
            await hre.network.provider.send('evm_setIntervalMining', [0]);
            await hre.network.provider.send('evm_setAutomine', [true]);
        } else {
            console.log("Disabling automining and enabling interval mining with", ms, "ms");
            await hre.network.provider.send('evm_setAutomine', [false]);
            await hre.network.provider.send('evm_setIntervalMining', [ms]);
        }
    });


// =================
// UTILITY FUNCTIONS
// =================

async function sleep(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// default export
export default config;
