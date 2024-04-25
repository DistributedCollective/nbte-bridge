import logging
import math

import requests

from .rpc import BitcoinRPC
from .types import BitcoinNetwork, is_bitcoin_network

logger = logging.getLogger(__name__)


class BitcoinFeeEstimator:
    def __init__(self, *, network: BitcoinNetwork, rpc: BitcoinRPC):
        self._network = network
        self._mempool_space_fee_estimator = MempoolSpaceFeeEstimator(network=network)
        self._rpc_fee_estimator = BitcoinRpcFeeEstimator(network=network, rpc=rpc)

    def get_fee_sats_per_vb(self):
        if self._network != "regtest":
            try:
                return self._mempool_space_fee_estimator.get_fee_sats_per_vb()
            except Exception:
                logger.exception(
                    "Failed to fetch fee from mempool.space (only a warning, ignored), falling back to bitcoind"
                )

        try:
            return self._rpc_fee_estimator.get_fee_sats_per_vb()
        except Exception:
            logger.exception("Failed to fetch fee from bitcoind (only a warning, ignored)")

        raise ValueError("Failed to fetch fee from both mempool.space and bitcoind")


class MempoolSpaceFeeEstimator:
    def __init__(
        self,
        *,
        network: BitcoinNetwork,
    ):
        if not is_bitcoin_network(network):
            raise ValueError(f"Invalid network: {network}")

        self._network = network
        self._mempool_url = "https://mempool.space"
        if self._network != "mainnet":
            self._mempool_url += f"/{self._network}"

    def get_fee_sats_per_vb(self):
        # Original from bidi fastbtc
        # private async fetchFeeSatsPerVBFromMempoolSpace(): Promise<number> {
        #     let url: string;
        #     if (this.network === networks.testnet) {
        #         url = 'https://mempool.space/testnet/api/v1/fees/recommended';
        #     } else {
        #         // might as well use the real fee for regtest *__*
        #         url = 'https://mempool.space/api/v1/fees/recommended';
        #     }
        #     const response = await http.getJson(url);
        #     const ret = response.fastestFee;
        #     if (typeof ret !== 'number') {
        #         throw new Error(`Unexpected response from mempool.space: ${JSON.stringify(response)}`);
        #     }
        #     return ret;
        # }
        if self._network == "regtest":
            raise ValueError("cannot fetch regtest fees from mempool.space")

        resp = requests.get(f"{self._mempool_url}/api/v1/fees/recommended")
        resp.raise_for_status()
        data = resp.json()
        return data["fastestFee"]


class BitcoinRpcFeeEstimator:
    def __init__(self, *, network: BitcoinNetwork, rpc: BitcoinRPC):
        self._network = network
        self._rpc = rpc

    def get_fee_sats_per_vb(self) -> int:
        return math.ceil(self.get_fee_btc_ber_kb() / 1000 * 1e8)

    def get_fee_btc_ber_kb(self) -> float:
        # Original from bidi fastbtc
        # public async estimateFeeBtcPerKB(): Promise<number> {
        #     // We aim to get a fee that will get us into the next block, but it doesn't always work.
        #     let estimateRawFeeOutput = await this.nodeWrapper.call('estimaterawfee', [1]);
        #     let feeBtcPerKB = estimateRawFeeOutput.short.feerate;
        #     if (typeof feeBtcPerKB === 'number') {
        #         // It worked -- yay. Cache and return it.
        #         this.cachedFeeBtcPerKB = feeBtcPerKB;
        #         return feeBtcPerKB;
        #     } else if (this.network === networks.regtest) {
        #         // estimateRawFee doesn't work on regtest
        #         return 10 / 1e8 * 1000;
        #     } else {
        #         // It didn't work. We cannot always estimate the fee for two blocks.
        #         // Here we will fall back on the higher of the cached fee and the estimated fee for two blocks
        #         const response1 = JSON.stringify(estimateRawFeeOutput);
        #         this.logger.warn(
        #             `estimaterawfee 1 failed with response ${response1} -- falling back to estimaterawfee 2`
        #         );

        #         let estimateRawFeeIn2BlocksOutput = await this.nodeWrapper.call('estimaterawfee', [2]);
        #         let feeIn2BlocksBtcPerKB = estimateRawFeeIn2BlocksOutput.short.feerate;
        #         if (typeof feeIn2BlocksBtcPerKB === 'number') {
        #             if (this.cachedFeeBtcPerKB) {  // we could compare to undefined, but 0
        #                                            // and null don't seem right either
        #                 return Math.max(this.cachedFeeBtcPerKB, feeIn2BlocksBtcPerKB);
        #             } else {
        #                 // If we don't have the cached fee, reluctantly use the 2 blocks fee (and cache it)
        #                 this.cachedFeeBtcPerKB = feeIn2BlocksBtcPerKB;
        #                 return feeIn2BlocksBtcPerKB;
        #             }
        #         } else {
        #             const response2 = JSON.stringify(estimateRawFeeIn2BlocksOutput);
        #             throw new Error(
        #                 `Unable to deduce gas fee, got ${response1} for response for estimaterawfee1 ` +
        #                 `and ${response2} for response from estimaterawfee 2 from the btc node`
        #             );
        #         }
        #     }
        # }
        if self._network == "regtest":
            return 10 / 1e8 * 1000
        response_1 = self._rpc.call("estimaterawfee", [1])
        fee_btc_per_kb = response_1["short"].get("feerate")
        if fee_btc_per_kb:
            return fee_btc_per_kb

        logger.warning(f"estimaterawfee 1 failed with response {response_1} -- falling back to estimaterawfee 2")
        response_2 = self._rpc.call("estimaterawfee", [2])
        fee_in_2_blocks_btc_per_kb = response_2["short"].get("feerate")
        if fee_in_2_blocks_btc_per_kb:
            return fee_in_2_blocks_btc_per_kb

        raise ValueError(
            f"Unable to deduce gas fee, got {response_1} for response for estimaterawfee1 "
            + f"and {response_2} for response from estimaterawfee 2 from the btc node"
        )
