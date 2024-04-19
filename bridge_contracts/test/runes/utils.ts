import { setStorageAt, getStorageAt } from "@nomicfoundation/hardhat-network-helpers";
import { ethers } from 'hardhat';
import { Contract, BigNumberish, Signer } from 'ethers';

const RUNE_TOKEN_BALANCE_MAPPING_SLOT = 0;
const RUNE_TOKEN_TOTAL_SUPPLY_SLOT = 2;

export async function setRuneTokenBalance(
    runeToken: Contract | string,
    user: Signer | Contract | string,
    balance: BigNumberish
) {
    const runeTokenAddress = typeof runeToken === 'string' ? runeToken : await runeToken.getAddress();
    const userAddress = typeof user === 'string' ? user : await user.getAddress();

    const balanceSlot = ethers.solidityPackedKeccak256(
        ["uint256", "uint256"],
        [userAddress, RUNE_TOKEN_BALANCE_MAPPING_SLOT]
    );

    const balanceBefore = BigInt(
        await getStorageAt(
            runeTokenAddress,
            balanceSlot,
        )
    );
    const totalSupplyBefore = BigInt(
        await getStorageAt(
            runeTokenAddress,
            RUNE_TOKEN_TOTAL_SUPPLY_SLOT,
        )
    );

    const balanceDiff = BigInt(balance) - balanceBefore;

    await setStorageAt(
        runeTokenAddress,
        balanceSlot,
        balance
    );
    await setStorageAt(
        runeTokenAddress,
        RUNE_TOKEN_TOTAL_SUPPLY_SLOT,
        totalSupplyBefore + balanceDiff,
    );
}

export function reasonNotRole(address: string, role: string): string {
    return `AccessControl: account ${address.toLowerCase()} is missing role ${role}`;
}

export function reasonNotAdmin(address: string): string {
    return reasonNotRole(address, "0x0000000000000000000000000000000000000000000000000000000000000000");
}

export function reasonNotPauser(address: string): string {
    return reasonNotRole(address, "0x539440820030c4994db4e31b6b800deafd503688728f932addfe7a410515c14c");
}

export function reasonNotGuard(address: string): string {
    return reasonNotRole(address, "0x25bca7788d8c23352e368ccd4774eb5b5fc3d40422de2c14e98631ab71f33415");
}
