import {
  time,
  loadFixture,
} from "@nomicfoundation/hardhat-toolbox/network-helpers";
import { anyValue } from "@nomicfoundation/hardhat-chai-matchers/withArgs";
import { expect } from "chai";
import { ethers } from "hardhat";

describe("TapUtils", function () {
  async function deployTapBridgeFixture() {
    const TapUtils = await ethers.getContractFactory("TapUtils");
    const tapUtils = await TapUtils.deploy('taprt');

    return { tapUtils };
  }

  describe("address decoding", function () {
    it("Should decode a tap address", async function () {
      const {tapUtils} = await loadFixture(deployTapBridgeFixture);
      const address = 'taprt1qqqsqqspqqzzqjyk4c4p3hpqqegkqpwm3uecevcecasrttlre8hzhsqrsta80776qcssy7xzmvdw2evav6qk9qe925v4vzkzf5c6gnnr0pe3dxqkqxr6u7cfpqss8gufykfm9mcgmmw5w5a6lrk8x09rhknq25xvvvevsjqj4y0c54ezpgpl6pxjpshksctndpkkz6tv8ghj7mtpd9kxymmc9e6x2undd9hxzmpwd35kw6r5de5kueeww3hkgcte8g6rgvcunxezy';
      const ret = await tapUtils.decodeTapAddress(
          address,
      );
      expect(ret.chainParamsHrp).to.equal('taprt');
      expect(ret.assetVersion).to.equal(0);
      expect(ret.assetId).to.equal('0x4896ae2a18dc2006516005db8f338cb319c76035afe3c9ee2bc00382fa77fbda');
      expect(ret.groupKey).to.equal('0x');
      expect(ret.scriptKey).to.equal('0x0278c2db1ae5659d66816283255519560ac24d31a44e6378731698160187ae7b09');
      expect(ret.internalKey).to.equal('0x03a3892593b2ef08dedd4753baf8ec733ca3bda60550cc6332c84812a91f8a5722');
      expect(ret.tapscriptSibling).to.equal('0x');
      expect(ret.amount).to.equal(1234);
      expect(ret.assetType).to.equal('0x');
    });

    describe('readBigSize', () => {
      const bigSizeVectors = [
        {
          "name": "zero",
          "value": 0,
          "bytes": "00"
        },
        {
          "name": "one byte high",
          "value": 252,
          "bytes": "fc"
        },
        {
          "name": "two byte low",
          "value": 253,
          "bytes": "fd00fd"
        },
        {
          "name": "two byte high",
          "value": 65535,
          "bytes": "fdffff"
        },
        {
          "name": "four byte low",
          "value": 65536,
          "bytes": "fe00010000"
        },
        {
          "name": "four byte high",
          "value": '4294967295',
          "bytes": "feffffffff"
        },
        {
          "name": "eight byte low",
          "value": '4294967296',
          "bytes": "ff0000000100000000"
        },
        {
          "name": "eight byte high",
          "value": '18446744073709551615',
          "bytes": "ffffffffffffffffff"
        },
      ]
      for (const vector of bigSizeVectors) {
        it(`should read BigSize (${vector.name})`, async () => {
          const { tapUtils} = await loadFixture(deployTapBridgeFixture);
          const [value, newOffset] = await tapUtils.readBigSize(
              '0x' + vector.bytes,
              0
          );
          expect(value).to.equal(vector.value);
        });
      }
    });
  });

  describe("bech32 decoding", function () {
    // test vectors: https://github.com/bitcoinjs/bech32
    it("Should decode bech32", async function () {
      const { tapUtils} = await loadFixture(deployTapBridgeFixture);
      const words = await tapUtils.decodeBech32(
          'abcdef',
          'abcdef1qpzry9x8gf2tvdw0s3jn54khce6mua7lmqqqxw',
          1
      );
      const expectedWords =  [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31];
      const expectedWordsHex = '0x' + expectedWords.map((x) => x.toString(16).padStart(2, '0')).join('');
      expect(words).to.equal(expectedWordsHex);
    });

    it("Should decode bech32m", async function () {
      const { tapUtils} = await loadFixture(deployTapBridgeFixture);
      const words = await tapUtils.decodeBech32(
          'abcdef',
          'abcdef1l7aum6echk45nj3s0wdvt2fg8x9yrzpqzd3ryx',
          0x2bc830a3
      );
      const expectedWords =  [31,30,29,28,27,26,25,24,23,22,21,20,19,18,17,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0];
      const expectedWordsHex = '0x' + expectedWords.map((x) => x.toString(16).padStart(2, '0')).join('');
      expect(words).to.equal(expectedWordsHex);
    });

    it("Should decode a bech32m address", async function () {
      const { tapUtils} = await loadFixture(deployTapBridgeFixture);
      // 0001000220f8427a513ff7908947256653fd857c6a31928119d57449f0d00b649babde24a3042102bf90b0811883f83e02368340db5d3293535dae71b894cfa43f0bbb53330e85fe0621027aa8de1cffc9265b23ff98c39f0f4b3f26feb470c4c033a1e7ecfb732a32c99e0805fe499529d9
      const words = await tapUtils.decodeBech32Address(
          'taprt',
          'taprt1qqqsqq3qlpp855fl77ggj3e9veflmptudgce9qge646ynuxspdjfh277yj3sgggzh7gtpqgcs0uruq3ksdqdkhfjjdf4mtn3hz2vlfplpwa4xvcwshlqvggz025du88leyn9kgllnrpe7r6t8un0adrscnqr8g08anahx23jex0qsp07fx2jnkgz3skek',
          0x2bc830a3
      );
      const expectedWordsHex =  '0x0001000220f8427a513ff7908947256653fd857c6a31928119d57449f0d00b649babde24a3042102bf90b0811883f83e02368340db5d3293535dae71b894cfa43f0bbb53330e85fe0621027aa8de1cffc9265b23ff98c39f0f4b3f26feb470c4c033a1e7ecfb732a32c99e0805fe499529d9';
      expect(words).to.equal(expectedWordsHex);
    });

    it("Should decode segwit v0 address", async () => {
      const { tapUtils} = await loadFixture(deployTapBridgeFixture);
      await tapUtils.decodeBech32(
          'bc',
          'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4',
          1,
      );
    });

    it("Should decode segwit v1 address", async () => {
      const { tapUtils} = await loadFixture(deployTapBridgeFixture);
      await tapUtils.decodeBech32(
          'bc',
          'bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297',
          0x2bc830a3,
      );
    });
  });
});
