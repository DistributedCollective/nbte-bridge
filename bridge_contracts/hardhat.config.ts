import { HardhatUserConfig } from "hardhat/config";
import {task, types} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";

const config: HardhatUserConfig = {
    solidity: "0.8.19",
    networks: {
        "integration-test": {
            url: "http://localhost:18545",
        },
    }
};


// ==========
// DEPLOYMENT
// ==========

task("deploy-bridge")
    .addOptionalParam("owner", "Address of the owner", undefined, types.string)
    .addOptionalParam("fundAmount", "Decimal amount to fund the bridge with", "0", types.string)
    .setAction(async ({ owner, fundAmount }, hre) => {
        const ethers = hre.ethers;
        const fundAmountWei = ethers.parseEther(fundAmount);

        const bridge = await ethers.deployContract("Bridge", [], {
        });

        await bridge.waitForDeployment();

        console.log(
            `Bridge deployed to ${bridge.target}`
        );

        if (fundAmountWei) {
            console.log(`Funding bridge with ${fundAmountWei} wei`);
            const tx = await bridge.fund({ value: fundAmountWei });
            console.log('tx hash:', tx.hash, 'waiting for tx...');
            await tx.wait();
        }

        if (owner) {
            console.log(`Setting owner to ${owner}`);
            const tx = await bridge.transferOwnership(owner);
            console.log('tx hash:', tx.hash, 'waiting for tx...');
            await tx.wait();
        }
    });


// ============
// TEST HELPERS
// ============

task("transfer-to-btc")
    .addPositionalParam("bridgeAddress", "Address of the bridge contract")
    .addPositionalParam("amount", "Decimal amount to transfer", undefined, types.string)
    .addPositionalParam("btc-address", "Recipient BTC address")
    .addPositionalParam("from", "Address to transfer from (defaults to first account)")
    .setAction(async ({ bridgeAddress, amount, btcAddress, from }, hre) => {
        const ethers = hre.ethers;
        const bridge = await ethers.getContractAt("Bridge", bridgeAddress);

        const amountWei = ethers.parseEther(amount);
        console.log(`Transferring ${amount} wei to ${btcAddress}`);

        const tx = await bridge.transferToBtc(btcAddress, {
            value: amountWei,
            ...(from ? { from } : {}),
        });
        console.log('tx hash:', tx.hash, 'waiting for tx...');
        await tx.wait();
    });

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
