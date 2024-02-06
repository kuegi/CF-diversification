import json
import logging
import logging.handlers
import math
import os
import signal
import sys
from functools import reduce
from time import sleep

import requests as requests

NODE_URL = "http://127.0.0.1:8555/"
NODE_USER = "satoshi"
NODE_PASSWORD = "hunter12"

class Settings:
    def __init__(self, settings: dict):
        self.logToFile = settings.get('logToFile')
        self.logToConsole = settings.get('logToConsole')
        if "logId" in settings:
            self.logId = settings['logId']
        else:
            self.logId = "cfDiversification"
        self.address = settings.get("address")
        self.cfAddress = settings.get("cfAddress")
        self.maxSwapPerBlock = settings.get("maxSwapPerBlock")
        self.maxPercentMove = settings.get("maxPercentMove")
        self.targetRatio = settings.get("targetRatio")
        self.blockPeriod = settings.get("blockPeriod")
        self.forceStart = settings.get("forceStart")


def setup_logger(settings: Settings):
    name = settings.logId
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if len(logger.handlers) == 0:
        if settings.logToConsole:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(fmt='\r%(asctime)s - %(levelname)s:%(name)s - %(message)s'))
            logger.addHandler(handler)

        if settings.logToFile:
            base = 'logs/'
            try:
                if not os.path.exists(base):
                    os.makedirs(base)
            except Exception:
                pass
            fh = logging.handlers.RotatingFileHandler(base + name + '.log', mode='a', maxBytes=200 * 1024,
                                                      backupCount=50)
            fh.setFormatter(logging.Formatter(fmt='%(asctime)s - %(levelname)s - %(message)s'))
            fh.setLevel(logging.INFO)
            logger.addHandler(fh)

    return logger


def readSettings(settingsPath) -> Settings:
    global NODE_URL, NODE_USER, NODE_PASSWORD

    with open(settingsPath) as f:
        settings = json.load(f)

        if "NODE_URL" in settings:
            NODE_URL = settings["NODE_URL"]

        NODE_USER = settings['NODE_USER']
        NODE_PASSWORD = settings['NODE_PASSWORD']
        return Settings(settings)


def rpc(method, params=None):
    if params is None:
        params = []
    data = json.dumps({
        "jsonrpc": "2.0",
        "id": "1",
        "method": method,
        "params": params
    })
    result = requests.post(NODE_URL, auth=(NODE_USER, NODE_PASSWORD), data=data)
    if result.status_code >= 300:
        message = f"--Error in RPC Call {method} with {str(params)}:\n{result.json()['error']['message']}"
        logger.error(message)
    return result.json()['result']


def waitForTx(txId, loopSleep=1.0, timeoutBlocks=30):
    if txId is None:
        return False
    height = rpc('getblockcount')
    lastBlock = height + timeoutBlocks
    tx = rpc('gettransaction', [txId])
    while tx is not None and ("blockhash" not in tx) and (timeoutBlocks <= 0 or height <= lastBlock):
        height = rpc('getblockcount')
        print(f"\r{height} waiting for tx {txId}", end="")
        sleep(loopSleep)
        try:
            tx = rpc('gettransaction', [txId])
        except:
            print("\rconnection failed, waiting for reconnect 1 min", end="")
            sleep(60)
    return tx is not None and (timeoutBlocks <= 0 or height <= lastBlock)


def get_balance(address):
    utxos = rpc("listunspent", [0, 99999999, [address]])
    return reduce(lambda prev, utxo: prev + utxo["amount"], utxos, 0)


def get_tokens(address):
    tokens = rpc("getaccount", [settings.cfAddress])
    result = {}
    for token in tokens:
        parts = token.split("@")
        result[parts[1]] = float(parts[0])
    return result


def main_loop(settings: Settings):
    '''
    This requires that the CF address was added to the node via importaddress
    '''

    # first check if we have funds as tokens and not utxos
    utxos = get_balance(settings.address)
    if utxos > 1:
        param = {}
        param[settings.address] = f"{utxos - 1:.8f}@DFI"
        txId = rpc("utxostoaccount", [param])
        logger.info(f"converting {utxos - 1:.8f} utxos to token in {txId}")
        waitForTx(txId)
        utxos = get_balance(settings.address)

    dusdDFI = list(rpc("getpoolpair", ["DUSD-DFI"]).values())[0]
    dfiPerDUSD = dusdDFI["reserveB/reserveA"]
    maxSwapForMove = dusdDFI["reserveB"] * (math.sqrt(1 + settings.maxPercentMove / 100) - 1)

    # CF balances
    dfiInCF = get_balance(settings.cfAddress)
    cfTokens = get_tokens(settings.cfAddress)
    dusdInCF = cfTokens.get("DUSD") if "DUSD" in cfTokens else 0
    dfiTokenCF = cfTokens.get("DFI") if "DFI" in cfTokens else 0
    communityBalances = rpc("listcommunitybalances")
    dfiTokenCF = dfiTokenCF + communityBalances.get("CommunityDevelopmentFunds")

    # own balances
    myTokens = get_tokens(settings.address)
    myDUSD = myTokens.get("DUSD") if "DUSD" in cfTokens else 0
    myDFI = myTokens.get("DFI") if "DFI" in cfTokens else 0

    totalDFI = dfiInCF + dfiTokenCF + utxos + myDFI
    totalDUSDinDFI = (myDUSD + dusdInCF) * dfiPerDUSD
    maxDUSDPartinDFI = (totalDFI + totalDUSDinDFI) * settings.targetRatio
    swapAmount = min(maxDUSDPartinDFI - totalDUSDinDFI, settings.maxSwapPerBlock, maxSwapForMove, myDFI)
    if swapAmount > 0:
        txId = rpc("poolswap", [
            {
                "from": settings.address,
                "tokenFrom": "DFI",
                "amountFrom": f"{swapAmount:.8f}",
                "to": settings.cfAddress,
                "tokenTo": "DUSD"
            }
        ])
        logger.info(f"swapping {swapAmount:.8f} DFI in {txId}")


should_run = True


def sig_handler(sig, frame):
    global should_run
    logger.info("stopping script")
    should_run = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    settingsPath = sys.argv[1] if len(sys.argv) > 1 else None
    # read settings
    print("starting bot with settings from %s" % settingsPath)
    settings = readSettings(settingsPath)
    logger = setup_logger(settings)
    lastblock = rpc("getblockcount")
    if settings.forceStart:
        lastblock = 0
    logger.info(f"starting loop with lastblock {lastblock}")
    while should_run:
        currentblock = rpc("getblockcount")
        if currentblock >= lastblock + settings.blockPeriod:
            logger.info(f"executing at block {currentblock}")
            main_loop(settings)
            lastblock = currentblock
        sleep(10)

    logger.info("bot ended")