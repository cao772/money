# 私有对账

收到真实渠道对账单后，为每个账号、期间及币种准备一个私有 JSON 文件。填入该期间已核对的销售额、退款、平台及支付手续费、其他直接支出和凭证位置。金额使用十进制字符串。只有对清楚的零才填 `"0.00"`。未核对完整的期间先留在私有工作底稿。若到账币种与销售币种不同，原币对账的 payout 留空，另存原始结算凭证。

```json
{
  "id": "synthetic-statement",
  "account": "synthetic-store",
  "currency": "USD",
  "starts": "2025-01-01",
  "ends": "2025-01-31",
  "sales": "10.00",
  "refunds": "1.00",
  "fees": "0.80",
  "expenses": "2.00",
  "payout": null,
  "evidence": "synthetic fixture"
}
```

`python money.py statement .local/statement.json` 核对并登记。不要将本页合成示例导入真实账本。相同 ID 和内容可重试，同一账号、币种的重叠期间会提示冲突。单个账号可用一个稳定代号。共同成本只在一个期间归属一次。门槛、估价和待审批购买均不计为发生的费用。

`python money.py report` 按 USD、CNY、EUR 原币返回已登记期间的合计。实际收入等于销售额减退款，成本包括手续费和已归属支出，净利润为两者之差。到账额单独列报，填入 payout 时还需填写 payout_evidence。任一期间到账未知时，该币种的结算合计保持空值。尚无对账凭证时，收入、成本和净利润均为空值。
