import { HardhatUserConfig } from "hardhat/config";
import {task, types} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";

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
        const ethers = hre.ethers;

        const bridge = await ethers.deployContract(
            "Bridge",
            [
                '0x0000000000000000000000000000000000000000',
                2,
                [
                    '0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a',
                    '0x09dcD91DF9300a81a4b9C85FDd04345C3De58F48',
                    //'0xA40013a058E70664367c515246F2560B82552ACb',
                ],
            ],
            {}
        );
        await bridge.waitForDeployment();
        console.log(
            `Bridge deployed to ${bridge.target}`
        );

        const precompiledMintingContract = await ethers.deployContract(
            "PrecompiledMintingContractMock",
            [bridge.target],
            {}
        );
        await precompiledMintingContract.waitForDeployment();
        console.log(
            `PrecompiledMintingContractMock deployed to ${precompiledMintingContract.target}`
        );

        const btcAddressValidator = await ethers.deployContract("BTCAddressValidator", [
            'bcrt1',
            [
                "m", // pubkey hash
                "n", // pubkey hash
                "2", // script hash
            ],
        ], {});
        await btcAddressValidator.waitForDeployment();
        console.log(
            `BTCAddressValidator deployed to ${btcAddressValidator.target}`
        );

        console.log("Setting bridge parameters");
        let tx = await bridge.setPrecompiledMintingContract(precompiledMintingContract.target);
        console.log('tx hash (setPrecompiledMintingContract):', tx.hash, 'waiting for tx...');
        await tx.wait();
        tx = await bridge.setBtcAddressValidator(btcAddressValidator.target);
        console.log('tx hash (setBtcAddressValidator):', tx.hash, 'waiting for tx...');
        await tx.wait();

        const fundAmountWei = ethers.parseEther('123.0');
        console.log(`Funding PrecompiledMintingContractMock with ${fundAmountWei} wei`);
        tx = await precompiledMintingContract.fund({ value: fundAmountWei });
        console.log('tx hash:', tx.hash, 'waiting for tx...');
        await tx.wait();

        // temporarily set node1 as owner
        const owner = '0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a';
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
    .addParam("bridgeAddress", "Address of the bridge contract")
    .addParam("amount", "Decimal amount to transfer", undefined, types.string)
    .addParam("btcAddress", "Recipient BTC address")
    .addOptionalParam("from", "Address to transfer from (defaults to first account)")
    .setAction(async ({ bridgeAddress, amount, btcAddress, from }, hre) => {
        const ethers = hre.ethers;
        let bridge = await ethers.getContractAt("Bridge", bridgeAddress);
        if (from) {
            const signer = await ethers.getSigner(from);
            bridge = bridge.connect(signer);
        }

        const amountWei = ethers.parseEther(amount);
        console.log(`Transferring ${amount} BTC (${amountWei} wei) to ${btcAddress}`);

        const tx = await bridge.transferToBtc(btcAddress, {
            value: amountWei,
        });
        console.log('tx hash:', tx.hash, 'waiting for tx...');
        const receipt = await tx.wait();
        console.log('tx receipt:', receipt);
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
