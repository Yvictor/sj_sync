# language: zh-TW
#
# 主動回報 → Native Trade 欄位對應表（Shioaji 1.2.x / 1.3.x）
#
# 回報                         回報來源欄位                         要更新的 Native Trade 欄位
# New 成功                     operation.op_code                  status.status = Submitted
# New 失敗                     operation.op_code/op_msg           status.status = Failed，並更新 status_code/msg
# UpdatePrice 成功             status.modified_price             status.modified_price；order.price 保留原始委託價
# UpdateQty 成功               status.cancel_quantity            累加 status.cancel_quantity；order.quantity 保留原始委託量
# Cancel 成功                  status.cancel_quantity            status.status = Cancelled、累加 cancel_quantity、保留 modified_price
# StockDeal/FuturesDeal        price/quantity/exchange_seq/ts     status.status、deal_quantity、deals
# 非 New 委託失敗              operation.op_code/op_msg           只更新 status_code/msg，價格、數量與狀態不變
#
# 七個必要觀察欄位：
# status.status、order.price、order.quantity、status.modified_price、
# status.cancel_quantity、status.deal_quantity、status.deals

功能: 主動回報投影到 Native Trade 欄位
  作為使用 sj_sync 的交易程式
  我希望 Native Trade 在使用者 callback 執行前反映最新委託與成交回報
  以便不呼叫 update_status 也能讀到一致的 Trade 狀態

  背景:
    假設 Shioaji 1.2 或 1.3 的 Local Native Trade 初始狀態為 PendingSubmit，委託價 100.0，原始委託量 2

  場景: New 成功只把新單狀態更新為 Submitted
    當 收到 New 委託回報，op_code 00，order.price 100.0，order.quantity 2，modified_price 0.0，cancel_quantity 0
    那麼 Trade 七個欄位應為 status Submitted、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 0、deal_quantity 0、deals 0 筆

  場景: New 失敗把狀態更新為 Failed 並保留委託欄位
    當 收到 New 委託回報，op_code E001，order.price 100.0，order.quantity 2，modified_price 0.0，cancel_quantity 0
    那麼 Trade 七個欄位應為 status Failed、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 0、deal_quantity 0、deals 0 筆
    而且 Trade status_code 應為 E001，msg 應為 rejected

  場景: UpdatePrice 成功保留原始 order.price 並更新 modified_price
    假設 已收到 New 成功回報
    當 收到 UpdatePrice 委託回報，op_code 00，order.price 100.0，order.quantity 2，modified_price 101.0，cancel_quantity 0
    那麼 Trade 七個欄位應為 status Submitted、order.price 100.0、order.quantity 2、modified_price 101.0、cancel_quantity 0、deal_quantity 0、deals 0 筆
    而且 使用者 callback 觀察到 status Submitted、order.price 100.0、order.quantity 2、modified_price 101.0、cancel_quantity 0、deal_quantity 0、deals 0 筆

  場景: UpdateQty 成功保留原始委託量並增加 cancel_quantity
    假設 已收到 New 成功回報
    當 收到 UpdateQty 委託回報，op_code 00，order.price 100.0，order.quantity 2，modified_price 0.0，cancel_quantity 1
    那麼 Trade 七個欄位應為 status Submitted、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 1、deal_quantity 0、deals 0 筆

  場景: 第一筆 Deal 把 Trade 更新為 PartFilled 並新增 Deal
    假設 已收到 New 成功回報
    當 收到成交回報 exchange_seq D001，price 100.5，quantity 1
    那麼 Trade 七個欄位應為 status PartFilled、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 0、deal_quantity 1、deals 1 筆
    而且 第 1 筆 deal 應為 exchange_seq D001、price 100.5、quantity 1

  場景: 累計成交量達原始委託量時更新為 Filled
    假設 已收到 New 成功回報
    當 收到成交回報 exchange_seq D001，price 100.5，quantity 1
    而且 收到成交回報 exchange_seq D002，price 101.0，quantity 1
    那麼 Trade 七個欄位應為 status Filled、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 0、deal_quantity 2、deals 2 筆
    而且 第 2 筆 deal 應為 exchange_seq D002、price 101.0、quantity 1

  場景: Cancel 成功保留已成交資料並取消剩餘數量
    假設 已收到 New 成功回報
    當 收到成交回報 exchange_seq D001，price 100.5，quantity 1
    而且 收到 Cancel 委託回報，op_code 00，order.price 100.0，order.quantity 2，modified_price 0.0，cancel_quantity 1
    那麼 Trade 七個欄位應為 status Cancelled、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 1、deal_quantity 1、deals 1 筆

  場景: UpdateQty 後再 Cancel 會累加兩次刪除數量
    假設 已收到 New 成功回報
    當 收到 UpdateQty 委託回報，op_code 00，order.price 100.0，order.quantity 2，modified_price 0.0，cancel_quantity 1
    而且 收到 Cancel 委託回報，op_code 00，order.price 100.0，order.quantity 2，modified_price 0.0，cancel_quantity 1
    那麼 Trade 七個欄位應為 status Cancelled、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 2、deal_quantity 0、deals 0 筆
    而且 使用者 callback 觀察到 status Cancelled、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 2、deal_quantity 0、deals 0 筆

  場景: UpdatePrice 後再 Cancel 會保留原始價與最後改後價
    假設 已收到 New 成功回報
    當 收到 UpdatePrice 委託回報，op_code 00，order.price 100.0，order.quantity 2，modified_price 101.0，cancel_quantity 0
    而且 收到 Cancel 委託回報，op_code 00，order.price 100.0，order.quantity 2，modified_price 0.0，cancel_quantity 2
    那麼 Trade 七個欄位應為 status Cancelled、order.price 100.0、order.quantity 2、modified_price 101.0、cancel_quantity 2、deal_quantity 0、deals 0 筆
    而且 使用者 callback 觀察到 status Cancelled、order.price 100.0、order.quantity 2、modified_price 101.0、cancel_quantity 2、deal_quantity 0、deals 0 筆

  場景: UpdatePrice 失敗只更新錯誤資訊而不改價格與狀態
    假設 已收到 New 成功回報
    當 收到 UpdatePrice 委託回報，op_code E002，order.price 100.0，order.quantity 2，modified_price 101.0，cancel_quantity 0
    那麼 Trade 七個欄位應為 status Submitted、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 0、deal_quantity 0、deals 0 筆
    而且 Trade status_code 應為 E002，msg 應為 rejected

  場景: 相同 exchange_seq 的 Deal 重送時不得重複累加
    假設 已收到 New 成功回報
    當 收到成交回報 exchange_seq D001，price 100.5，quantity 1
    而且 再次收到相同成交回報 exchange_seq D001，price 100.5，quantity 1
    那麼 Trade 七個欄位應為 status PartFilled、order.price 100.0、order.quantity 2、modified_price 0.0、cancel_quantity 0、deal_quantity 1、deals 1 筆
