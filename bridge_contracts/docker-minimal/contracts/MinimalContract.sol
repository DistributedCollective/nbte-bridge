// SPDX-License-Identifier: GPL-3.0-or-later-or-later
// This file is here to speed up the docker build (it allows it to download the solidity version in a previous
// stage). Keep the solidity version in line with what's actually used.
pragma solidity ^0.8.9;

contract MinimalContract {
}
