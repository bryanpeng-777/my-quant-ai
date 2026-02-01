"""
纳斯达克前100股票扫描脚本
扫描纳斯达克市值排名前100的股票，找出满足买入条件的股票
"""
from datetime import datetime
import time
from stock_utils import (
    get_stock_analysis,
    count_rules_passed,
    format_stock_analysis_text,
    call_deepseek_api,
    send_email,
    handle_pipeline_error
)

# ==========================================
# 买入规则阈值：满足至少N个规则才认为值得买入
# ==========================================
MIN_RULES_PASSED = 10  # 必须全部条件满足才建议买入（共 10 条规则）

def get_nasdaq_top100_symbols():
    """
    获取纳斯达克市值排名前100的股票代码列表
    使用纳斯达克100成分股列表（Nasdaq-100指数成分股）
    """
    # 纳斯达克100指数成分股列表（2024年更新）
    # 这些是纳斯达克交易所市值最大的100只非金融类股票
    nasdaq_100_symbols = [
        "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "GOOG", "META", "TSLA",
        "AVGO", "COST", "NFLX", "AMD", "PEP", "ADBE", "CSCO", "CMCSA",
        "INTC", "INTU", "AMGN", "TXN", "AMAT", "HON", "ISRG", "BKNG",
        "VRTX", "ADI", "GILD", "REGN", "LRCX", "SNPS", "CDNS", "KLAC",
        "ADP", "CTSH", "NXPI", "FTNT", "ON", "PAYX", "MRVL", "IDXX",
        "DXCM", "BKR", "FAST", "ANSS", "CPRT", "CRWD", "CTAS", "ENPH",
        "ODFL", "CDW", "TEAM", "ZS", "MCHP", "MELI", "ALGN", "FANG",
        "PCAR", "ROST", "KDP", "GEHC", "AEP", "DLTR", "EXC", "XEL",
        "EA", "WBD", "VRSK", "ILMN", "TTD", "DDOG", "MDB", "DOCN",
        "NET", "FTNT", "PANW", "OKTA", "ZM", "DOCU", "COUP", "NOW",
        "SNOW", "PLTR", "RBLX", "U", "BILL", "AFRM", "HOOD", "SOFI",
        "UPST", "LCID", "RIVN", "FRSH", "GTLB", "ASAN", "ESTC", "PATH",
        "CFLT", "APP", "AI", "CARM", "BMBL", "BAND", "BIDU", "JD"
    ]
    
    # 如果列表不足100个，补充一些其他纳斯达克大市值股票
    if len(nasdaq_100_symbols) < 100:
        additional_symbols = [
            "QCOM", "MU", "LRCX", "SWKS", "QRVO", "MCHP", "MPWR", "OLED",
            "ALKS", "INCY", "BIIB", "CELG", "ILMN", "SGEN", "VRTX", "EXAS",
            "NTES", "PDD", "BABA", "NIO", "XPEV", "LI", "BILI", "TME"
        ]
        nasdaq_100_symbols.extend(additional_symbols)
    
    # 去重并返回前100个
    unique_symbols = list(dict.fromkeys(nasdaq_100_symbols))  # 保持顺序的去重
    return unique_symbols[:100]

def generate_ai_report(stocks_data, total_worthy_count):
    """
    将扫描结果喂给 DeepSeek，让它生成专业投研结论
    
    Args:
        stocks_data: 字典列表，每个元素包含股票分析数据（只包含前5只股票）
        total_worthy_count: 总共满足条件的股票数量
    
    Returns:
        AI 生成的报告内容
    """
    # 构建所有股票的分析数据字符串（只包含前5只）
    stocks_analysis = []
    for data in stocks_data:
        rules_passed = count_rules_passed(data)
        stock_info = format_stock_analysis_text(data)
        stock_info += f"综合结论: {'建议买入' if rules_passed >= MIN_RULES_PASSED else '持续观望'}\n"
        stocks_analysis.append(stock_info)
    
    all_stocks_text = "\n".join(stocks_analysis)
    
    prompt = f"""
    你是资深价值投资分析师，擅长量化趋势分析。
    
    以下是纳斯达克市值排名前100股票扫描结果：
    - 总共发现 {total_worthy_count} 只股票满足买入条件（至少满足{MIN_RULES_PASSED}个检验项）
    - 以下仅展示满足规则数量最多的前5只股票的详细分析数据：
    
    {all_stocks_text}
    
    请根据以上数据写一份专业的邮件报告。
    1. 标题为【纳斯达克前100股票扫描报告 - {datetime.now().strftime('%Y-%m-%d')}】
    2. 在报告开头说明：本次扫描共发现 {total_worthy_count} 只股票满足买入条件，以下仅展示满足规则数量最多的前5只股票的详细清单
    3. 对这5只股票分别进行如下操作：
       a. 首先列出当前这几个关键值的数值，方便我去对比数据的正确性
       b. 我希望检验的决定是否买入一只股票的检查清单项包括：
          - 10周线是否位于20周线之上
          - 当前股价是否处于20周线之上
          - 当前股价是否处于30周线之上
          - 30周线目前的趋势是向上吗
          - 个股横盘是否超过6周（纵向波动小于20个点）
          - 横盘期间的下跌成交量是否有缩量的趋势
          - 当前这一周的收盘价是否比上一周的收盘价高出5%个点
          - 当前这一周的成交量是否比上一周高
          - MACD线是否DIF线在DEA线之上
          - 最近一周的收盘价是否是至少10周的最高价
       c. 针对上述所有项输出为一个清单，清单项为每一项校验是否通过，例如：
          10周线是否位于20周线之上：✅
          当前股价是否处于20周线之上：❌
    4. 最后给出这5只股票的综合对比分析和投资建议，按达成规则数量排序，优先推荐达成规则最多的股票
    """
    
    return call_deepseek_api(prompt)

def main():
    print(f"[{datetime.now()}] 启动纳斯达克前100股票扫描流水线...")
    
    try:
        # 1. 获取纳斯达克前100股票列表
        print(f"[{datetime.now()}] 正在获取纳斯达克市值排名前100的股票列表...")
        nasdaq_symbols = get_nasdaq_top100_symbols()
        print(f"[{datetime.now()}] 获取到 {len(nasdaq_symbols)} 只股票")
        
        # 2. 循环分析所有股票
        failed_stocks = []
        worthy_stocks = []  # 值得买入的股票（满足至少MIN_RULES_PASSED个规则）
        
        for idx, symbol in enumerate(nasdaq_symbols, 1):
            try:
                print(f"[{datetime.now()}] [{idx}/{len(nasdaq_symbols)}] 正在分析 {symbol}...")
                data = get_stock_analysis(symbol)
                
                if data is None:
                    print(f"[{datetime.now()}] ⚠️  {symbol} 数据不足或分析失败，跳过")
                    failed_stocks.append(symbol)
                    continue
                
                # 计算达成规则的数量
                rules_passed = count_rules_passed(data)
                print(f"[{datetime.now()}] {symbol} 分析完成，达成规则: {rules_passed}/10")
                
                # 如果满足买入条件，添加到值得买入列表
                if rules_passed >= MIN_RULES_PASSED:
                    worthy_stocks.append((symbol, rules_passed, data))
                    print(f"[{datetime.now()}] ✅ {symbol} 值得买入！达成 {rules_passed} 个规则")
                
                # 添加延迟以避免API限制
                time.sleep(0.5)
                
            except Exception as e:
                error_msg = str(e)
                print(f"[{datetime.now()}] ⚠️  {symbol} 分析失败: {error_msg}")
                failed_stocks.append(symbol)
                time.sleep(0.5)  # 即使失败也延迟一下
        
        # 3. 按达成规则数量排序
        worthy_stocks.sort(key=lambda x: x[1], reverse=True)
        total_worthy_count = len(worthy_stocks)
        
        # 只取前5只股票用于生成详细报告
        top5_stocks = worthy_stocks[:5]
        top5_stocks_data = [stock[2] for stock in top5_stocks]
        
        print(f"[{datetime.now()}] 扫描完成！")
        print(f"[{datetime.now()}] 总计分析: {len(nasdaq_symbols)} 只股票")
        print(f"[{datetime.now()}] 分析成功: {len(nasdaq_symbols) - len(failed_stocks)} 只")
        print(f"[{datetime.now()}] 分析失败: {len(failed_stocks)} 只")
        print(f"[{datetime.now()}] 值得买入: {total_worthy_count} 只（满足至少{MIN_RULES_PASSED}个规则）")
        
        if failed_stocks:
            print(f"[{datetime.now()}] 失败股票列表: {', '.join(failed_stocks[:10])}{'...' if len(failed_stocks) > 10 else ''}")
        
        if worthy_stocks:
            print(f"[{datetime.now()}] 值得买入的股票（按规则达成数排序，仅显示前10个）:")
            for symbol, rules_count, _ in worthy_stocks[:10]:
                print(f"  - {symbol}: {rules_count}/10 规则达成")
            if total_worthy_count > 5:
                print(f"[{datetime.now()}] 注意: 报告中将只显示前5只股票的详细清单")
        
        # 4. 如果有值得买入的股票，生成AI报告并发送邮件
        if top5_stocks_data:
            print(f"[{datetime.now()}] 正在生成 AI 分析报告（共 {total_worthy_count} 只值得买入的股票，报告中将详细展示前5只）...")
            report_content = generate_ai_report(top5_stocks_data, total_worthy_count)
            
            # 提取标题并发送
            lines = report_content.split('\n')
            subject = f"纳斯达克前100股票扫描报告 - {datetime.now().strftime('%Y-%m-%d')}"
            if lines and "【" in lines[0] and "】" in lines[0]:
                title_line = lines[0]
                if "【" in title_line:
                    subject = title_line.split("【")[1].split("】")[0] if "】" in title_line else subject
            
            send_email(subject, report_content)
            print(f"[{datetime.now()}] ✅ 流水线执行成功，报告已推送至邮箱。")
        else:
            print(f"[{datetime.now()}] ℹ️  本次扫描未发现满足买入条件的股票（需要至少满足{MIN_RULES_PASSED}个规则）")
            # 即使没有值得买入的股票，也可以发送一个简短的报告
            summary = f"""
纳斯达克前100股票扫描报告 - {datetime.now().strftime('%Y-%m-%d')}

扫描结果：
- 总计分析股票数: {len(nasdaq_symbols)}
- 成功分析: {len(nasdaq_symbols) - len(failed_stocks)} 只
- 分析失败: {len(failed_stocks)} 只
- 值得买入: 0 只（需要至少满足{MIN_RULES_PASSED}个规则）

本次扫描未发现满足买入条件的股票。建议继续观察市场变化。
            """
            send_email(f"纳斯达克前100股票扫描报告 - {datetime.now().strftime('%Y-%m-%d')}", summary)
            print(f"[{datetime.now()}] ✅ 扫描摘要已推送至邮箱。")
        
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)

if __name__ == "__main__":
    main()
