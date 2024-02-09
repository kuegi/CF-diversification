# CF-diversification
A bot to implement the special DFIP about CF-diversification on defichain

As a reference its implemented for different setups: 
* `ocean` contains a typescript version which can be run as an AWS lambda using ocean
* `python` contains a python script which should be run next to a fullnode. For this it is important to import the CF address to the node via `importaddress` (otherwise the bot can't see the utxos in the CF address)

## python version

Be aware that you need to run this on a clean wallet with only the bot address and CF addresses as watch only in it. This is needed because `utxostoaccount` ignores hints what utxo to use and therefor takes random utxos from your wallet, which would mess up the calculations.

be aware that loading the CF address into the wallet creates a 1.42 GB wallet.dat. and loading the utxos (listunspent) on that wallet requires defid to go to 14 GB of used ram.
