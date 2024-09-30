// SPDX-License-Identifier: GPL-3.0-or-later
pragma solidity 0.8.19;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "./TapUtils.sol";


contract Bridge is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    event TransferFromTap(
        uint256 indexed counter,
        address indexed to,
        address indexed rskToken,
        uint256 amountWei,
        bytes32 btcTxId,
        uint256 btcTxVout
    );

    event TransferToTap(
        uint256 indexed counter,
        address indexed from,
        string tapAddress
    );

    event FederatorAdded(
        address indexed account
    );

    event FederatorRemoved(
        address indexed account
    );

    struct BridgeableAsset {
        IERC20 rskToken;
        bytes32 tapAssetId;
        // TODO:
        // bytes32 genesisTxId;
        // uint8 genesisTxVout;
        // bytes tapGroupKey;
        uint256 tapAmountDivisor;
        bool tapNative;
        string tapAssetName;
    }

    event BridgeableAssetAdded(
        address rskToken,
        bytes32 tapAssetId,
        uint256 tapAmountDivisor,
        bool tapNative,
        string tapAssetName
    );

    event BridgeableAssetRemoved(
        address rskToken,
        bytes32 tapAssetId
    );

    mapping(address => BridgeableAsset) public assetsByRskTokenAddress;
    mapping(bytes32 => BridgeableAsset) public assetsByTaprootAssetId;
    // track procesed Tap->RSK transfers
    mapping(bytes32 => mapping(uint256 => bool)) public processedByBtcTxIdAndVout;

    BridgeableAsset[] public assets;

    uint256 public numRequiredSigners;
    address[] public federators;

    uint256 public numTransfersTotal;

    TapUtils public tapUtils;

    modifier onlyFederator() {
        require(isFederator(msg.sender), "only federator");
        _;
    }

    constructor(
        TapUtils _tapUtils,
        uint256 _numRequiredSigners,
        address[] memory _federators
    ) {
        tapUtils = _tapUtils;

        require(_numRequiredSigners <= _federators.length, "too many required signers");
        require(_numRequiredSigners > 0, "at least one signer required");
        numRequiredSigners = _numRequiredSigners;
        // check that there are no duplicates
        for (uint256 i = 0; i < _federators.length; i++) {
            for (uint256 j = i + 1; j < _federators.length; j++) {
                require(_federators[i] != _federators[j], "duplicate federator");
            }
            emit FederatorAdded(_federators[i]);
        }
        federators = _federators;
    }


    // Public API
    // ----------

    function transferToTap(
        string calldata receiverTapAddress
    )
    external
    nonReentrant
    {
        TapUtils.TapAddress memory tapAddress = tapUtils.decodeTapAddress(
            receiverTapAddress
        );

        BridgeableAsset memory asset = assetsByTaprootAssetId[tapAddress.assetId];
        require(address(asset.rskToken) != address(0), "asset not found");

        uint256 rskAmount = tapAddress.amount * asset.tapAmountDivisor;
        require(rskAmount > 0, "amount must be greater than 0");

        // TODO: burn native tokens
        asset.rskToken.safeTransferFrom(msg.sender, address(this), rskAmount);

        numTransfersTotal++;
        emit TransferToTap(
            numTransfersTotal,
            msg.sender,
            receiverTapAddress
        );
    }

    // Federator API
    // -------------

    function acceptTransferFromTap(
        address to,
        string calldata transferTapAddress,
        bytes32 btcTxId,
        uint256 btcTxVout,
        bytes[] memory signatures
    )
    external
    onlyFederator
    nonReentrant
    {
        // validate it's not already processed
        require(!processedByBtcTxIdAndVout[btcTxId][btcTxVout], "already processed");

        // address decoding
        TapUtils.TapAddress memory tapAddress = tapUtils.decodeTapAddress(
            transferTapAddress
        );
        BridgeableAsset memory asset = assetsByTaprootAssetId[tapAddress.assetId];
        if (address(asset.rskToken) == address(0)) {
            revert("asset not found");
        }
        uint256 rskAmount = tapAddress.amount * asset.tapAmountDivisor;
        require(rskAmount > 0, "amount must be greater than 0");

        // signature validation
        _validateTransferFromTapSignatures(
            to,
            transferTapAddress,
            btcTxId,
            btcTxVout,
            signatures
        );

        processedByBtcTxIdAndVout[btcTxId][btcTxVout] = true;

        // todo: mint tap-native assets
        asset.rskToken.safeTransfer(to, rskAmount);

        numTransfersTotal++;
        emit TransferFromTap(
            numTransfersTotal,
            to,
            address(asset.rskToken),
            rskAmount,
            btcTxId,
            btcTxVout
        );
    }

    function _validateTransferFromTapSignatures(
        address to,
        string calldata transferTapAddress,
        bytes32 btcTxId,
        uint256 btcTxVout,
        bytes[] memory signatures
    )
    internal
    view
    {
        // signature validation
        bytes32 signedMessageHash = ECDSA.toEthSignedMessageHash(
            getTransferFromTapMessageHash(
                to,
                transferTapAddress,
                btcTxId,
                btcTxVout
            )
        );

        address[] memory seen = new address[](signatures.length);
        uint256 numConfirmations = 0;
        bool selfSigned = false;

        for (uint256 i = 0; i < signatures.length; i++) {
            address recovered = ECDSA.recover(signedMessageHash, signatures[i]);
            require(recovered != address(0), "recover failed");
            require(isFederator(recovered), "not a federator");
            for (uint256 j = 0; j < i; j++) {
                require(seen[j] != recovered, "already signed by federator");
            }
            seen[i] = recovered;
            numConfirmations++;
            if (recovered == msg.sender) {
                selfSigned = true;
            }
        }

        // if the sender's signature was not among signatures, add one confirmation for implicit self-sign
        if (!selfSigned) {
            numConfirmations++;
        }

        require(numConfirmations >= numRequiredSigners, "not enough confirmations");
    }

    // Views/utilities
    // ---------------

    function getFederators()
    external
    view
    returns (address[] memory) {
        return federators;
    }

    function isFederator(
        address account
    )
    public
    view
    returns (bool)
    {
        for (uint256 i = 0; i < federators.length; i++) {
            if (federators[i] == account) {
                return true;
            }
        }
        return false;

    }

    function isProcessed(
        bytes32 btcTxId,
        uint256 btcTxVout
    )
    public
    view
    returns (bool)
    {
        return processedByBtcTxIdAndVout[btcTxId][btcTxVout];
    }

    function getTransferFromTapMessageHash(
        address to,
        string calldata transferTapAddress,
        bytes32 btcTxId,
        uint256 btcTxVout
    )
    public
    view
    returns (bytes32)
    {
        return keccak256(abi.encodePacked(
            "transferFromTap:",
            address(this),
            ":",
            to,
            ":",
            transferTapAddress,
            ":",
            btcTxId,
            ":",
            btcTxVout
        ));
    }

    // Owner API
    // ---------

    function addBridgeableAsset(
        IERC20 _rskToken,
        bytes32 _tapAssetId,
        uint256 _tapAmountDivisor,
        bool _tapNative,
        string calldata _tapAssetName
    ) external onlyOwner {
        require(address(_rskToken) != address(0), "invalid token address");
        require(_tapAssetId != bytes32(0), "invalid asset id");
        require(address(assetsByRskTokenAddress[address(_rskToken)].rskToken) == address(0), "token already added");
        require(address(assetsByTaprootAssetId[_tapAssetId].rskToken) == address(0), "asset id already added");
        for (uint256 i = 0; i < assets.length; i++) {
            require(assets[i].tapAssetId != _tapAssetId, "asset id already added (2)");
            require(address(assets[i].rskToken) != address(_rskToken), "token already added (2)");
        }
        BridgeableAsset memory asset = BridgeableAsset({
            rskToken: _rskToken,
            tapAssetId: _tapAssetId,
            tapAmountDivisor: _tapAmountDivisor,
            tapNative: _tapNative,
            tapAssetName: _tapAssetName
        });
        assetsByRskTokenAddress[address(_rskToken)] = asset;
        assetsByTaprootAssetId[_tapAssetId] = asset;
        assets.push(asset);
        emit BridgeableAssetAdded(
            address(_rskToken),
            _tapAssetId,
            _tapAmountDivisor,
            _tapNative,
            _tapAssetName
        );
    }

    function removeBridgeableAsset(
        address _rskTokenAddress
    ) external onlyOwner {
        BridgeableAsset memory asset = assetsByRskTokenAddress[_rskTokenAddress];
        require(address(asset.rskToken) != address(0), "token not found");
        delete assetsByRskTokenAddress[_rskTokenAddress];
        delete assetsByTaprootAssetId[asset.tapAssetId];
        for (uint256 i = 0; i < assets.length; i++) {
            if (assets[i].tapAssetId == asset.tapAssetId) {
                assets[i] = assets[assets.length - 1];
                assets.pop();
                break;
            }
        }
        emit BridgeableAssetRemoved(
            address(asset.rskToken),
            asset.tapAssetId
        );
    }

    function addFederator(
        address account
    )
    external
    onlyOwner
    {
        require(!isFederator(account), "already a federator");
        federators.push(account);
        emit FederatorAdded(account);
    }

    function removeFederator(
        address account
    )
    external
    onlyOwner
    {
        require(isFederator(account), "not a federator");
        uint256 index = 0;
        while (federators[index] != account) {
            index++;
        }
        federators[index] = federators[federators.length - 1];
        federators.pop();
        emit FederatorRemoved(account);
    }

    function setNumRequiredSigners(
        uint256 _numRequiredSigners
    )
    external
    onlyOwner
    {
        require(_numRequiredSigners <= federators.length, "too many required signers");
        numRequiredSigners = _numRequiredSigners;
    }

    function setTapUtils(
        TapUtils _tapUtils
    )
    external
    onlyOwner
    {
        tapUtils = _tapUtils;
    }
}
