def test_rsk_to_btc(user_web3, user_account):
    assert user_web3.eth.get_balance(user_account.address) == user_web3.to_wei(1, "ether")
