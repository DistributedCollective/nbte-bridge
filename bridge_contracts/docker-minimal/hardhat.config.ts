// This file is here to speed up the docker and should not be used from anywhere
import { HardhatUserConfig } from "hardhat/config";

const config: HardhatUserConfig = {
    solidity: {
        compilers: [
            {
                version: "0.8.19"
            },
        ],
    },
};

export default config;
