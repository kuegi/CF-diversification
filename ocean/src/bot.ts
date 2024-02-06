import { SSM } from 'aws-sdk'
import { BigNumber } from '@defichain/jellyfish-api-core'
import { ParameterList } from 'aws-sdk/clients/ssm'
import { MainNet, Network, TestNet } from '@defichain/jellyfish-network'
import { WhaleApiClient } from '@defichain/whale-api-client'
import { WIF } from '@defichain/jellyfish-crypto'
import { WalletClassic } from '@defichain/jellyfish-wallet-classic'
import { fromAddress, fromScript } from '@defichain/jellyfish-address'
import { WhaleWalletAccount, WhaleWalletAccountProvider } from '@defichain/whale-api-wallet'

class Settings {
  cfAddress: string = ''
  ownAddress: string = ''
  privateKey: string = ''
  maxPerExecution: number = 0
  maxMovePercent: number = 0
}

async function readParams(): Promise<Settings> {
  const ssm = new SSM()
  let params: ParameterList = []
  const keys = ['cfAddress', 'ownAddress', 'maxPerExecution', 'maxMovePercent']

  params =
    (
      await ssm
        .getParameters({
          Names: keys,
        })
        .promise()
    ).Parameters ?? []

  const settings = new Settings()
  settings.cfAddress = params.find((e) => e.Name == 'cfAddress') as string
  settings.ownAddress = params.find((e) => e.Name == 'ownAddress') as string
  settings.maxPerExecution = params.find((e) => e.Name == 'maxPerExecution') as number
  settings.maxMovePercent = params.find((e) => e.Name == 'maxMovePercent') as number
  settings.privateKey =
    (
      await ssm
        .getParameter({
          Name: 'privateKey',
          WithDecryption: true,
        })
        .promise()
    )?.Parameter?.Value ?? ''
  return settings
}

export async function main(event: Object, context: any): Promise<Object> {
  const params = await readParams()
  const network = params.ownAddress.startsWith('tf1') ? TestNet : MainNet
  const client = new WhaleApiClient({
    url: `https://${network.name}.ocean.jellyfishsdk.com`,
    version: 'v0',
    network: network.name,
  })
  const account = new WhaleWalletAccount(client, new WalletClassic(WIF.asEllipticPair(params.privateKey)), network)

  const dusdDFI = await client.poolpairs.get('DUSD-DFI')!
  const dusdId = dusdDFI.tokenA.id
  //get DFI balance of CF
  const cfFunds = await client.address.getBalance(params.cfAddress)
  const cfTokens = await client.address.listToken(params.cfAddress)
  const myDFI = await client.address.getBalance(params.ownAddress)
  const ownTokens = await client.address.listToken(params.ownAddress)
  const totalDFI = BigNumber.sum(
    cfFunds,
    cfTokens.find((t) => +t.id == 0)?.amount ?? 0,
    myDFI,
    ownTokens.find((t) => +t.id == 0)?.amount ?? 0,
  )
  const totalDUSD = BigNumber.sum(
    cfTokens.find((t) => t.id == dusdId)?.amount ?? 0,
    ownTokens.find((t) => t.id == dusdId)?.amount ?? 0,
  )

  const DUSDinDFI = totalDUSD.times(dusdDFI.priceRatio.ba)
  const ratioOfDUSD = DUSDinDFI.div(DUSDinDFI.plus(totalDFI))

  const myScript = fromAddress(params.ownAddress, network.name)!.script
  if (+myDFI > 1) {
    //transfer UTXO to DFI first
    const txId = await account
      .withTransactionBuilder()
      .account.utxosToAccount(
        { to: [{ script: myScript, balances: [{ token: 0, amount: new BigNumber(myDFI).minus(1) }] }] },
        myScript,
      )
    //TODO: wait for txId
  }

  //max value for ratio below 30%
  //max value for max Amount
  //max value for max percent
  //max amount based on balance

  const swapAmount = new BigNumber(0)

  //swap
  await account.withTransactionBuilder().dex.poolSwap(
    {
      fromScript: myScript,
      fromTokenId: 0,
      fromAmount: swapAmount,
      toScript: fromAddress(params.cfAddress, network.name)!.script,
      toTokenId: +dusdDFI.tokenA.id,
      maxPrice: new BigNumber(999999999),
    },
    myScript,
  )

  return {}
}
