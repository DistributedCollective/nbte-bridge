import {task} from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";
import {jsonAction} from '../base';

const PREFIX = 'tap-'

task(`${PREFIX}deploy-regtest`)
    .setAction(jsonAction(async ({}, hre) => {
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

        const tapUtils = await ethers.deployContract(
            "TapUtils",
            ["taprt"],
            {}
        );
        await tapUtils.waitForDeployment();
        console.log(
            `TapUtils deployed to ${tapUtils.target}`
        );

        console.log("Setting bridge parameters");
        let tx = await bridge.setTapUtils(tapUtils.target);
        console.log('tx hash (setTapUtils):', tx.hash, 'waiting for tx...');
        await tx.wait();

        // temporarily set node1 as owner
        const owner = '0x4091663B0a7a14e35Ff1d6d9d0593cE15cE7710a';
        if (owner) {
            console.log(`Setting owner to ${owner}`);
            const tx = await bridge.transferOwnership(owner);
            console.log('tx hash:', tx.hash, 'waiting for tx...');
            await tx.wait();
        }

        return {
            addresses: {
                TapBridge: bridge.target,
            }
        }
    }));
