"""
多市场股票买入分析脚本
分析指定股票是否满足买入条件，生成AI报告并发送邮件
支持美股(US)和港股(HK)
"""
from datetime import datetime
from stock_utils import (
    MARKET_US,
    MARKET_HK,
    get_config,
    get_stock_analysis,
    count_rules_passed,
    format_stock_analysis_text,
    call_deepseek_api,
    send_email,
    handle_pipeline_error,
    get_market_name,
    get_currency_symbol
)

# ==========================================
# 股票代码配置：在此添加要分析的股票代码
# 格式: {市场类型: [股票代码列表]}
# ==========================================
STOCK_CONFIG = {
    # 美股列表
    MARKET_US: [
        "NVDA",   # 英伟达
        "AAPL",   # 苹果
        "TSLA",   # 特斯拉
        "GOOGL",  # 谷歌
        "KO",     # 可口可乐
        "JD",     # 京东
        "BABA",   # 阿里
        "EDU",    # 新东方
        "BEKE",   # 贝壳
        "NTES",   # 网易
        "TSM",    # 台积电
        "NKE",    # 耐克
        "VOO",    # Vanguard S&P 500 ETF
    ],
    # 港股列表
    MARKET_HK: [
        "0700",   # 腾讯控股
        "9988",   # 阿里巴巴-SW
        "3690",   # 美团
        "1810",   # 小米集团
        "1024",   # 快手
        "9618",   # 京东集团-SW
        "9888",   # 百度集团-SW
        "9999",   # 网易-S
        "9868",   # 小鹏汽车-W
        "2015",   # 理想汽车-W
        "2331",   # 李宁
        "2020",   # 安踏体育
        "02800"
    ],
}

# 买入规则阈值
MIN_RULES_PASSED = 6

def generate_ai_report(stocks_data):
    """
    将多只股票的量化结果喂给 DeepSeek，让它生成专业投研结论
    
    Args:
        stocks_data: 字典，格式为 {(market, symbol): data_dict, ...}
    
    Returns:
        AI 生成的报告内容
    """
    # 统计各市场股票数量
    us_count = sum(1 for (m, _) in stocks_data.keys() if m == MARKET_US)
    hk_count = sum(1 for (m, _) in stocks_data.keys() if m == MARKET_HK)
    
    # 构建所有股票的分析数据字符串
    stocks_analysis = []
    for (market, symbol), data in stocks_data.items():
        rules_passed = count_rules_passed(data)
        stock_info = format_stock_analysis_text(data, symbol, market)
        stock_info += f"综合结论: {'建议买入' if rules_passed >= MIN_RULES_PASSED else '持续观望'}\n"
        stocks_analysis.append(stock_info)
    
    all_stocks_text = "\n".join(stocks_analysis)
    
    # 构建市场描述
    market_desc = []
    if us_count > 0:
        market_desc.append(f"美股 {us_count} 只")
    if hk_count > 0:
        market_desc.append(f"港股 {hk_count} 只")
    market_summary = "、".join(market_desc)
    
    prompt = f"""
    你是资深价值投资分析师，擅长量化趋势分析，熟悉美股和港股市场。
    
    以下是需要分析的股票列表（共 {len(stocks_data)} 只，包含 {market_summary}）：
    {all_stocks_text}
    
    请根据以上数据写一份专业的邮件报告。
    1. 标题为【Hello！Analysis Your Business】
    2. 对每一只参与分析的个股分别进行如下操作：
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
    3. 最后给出所有股票的综合对比分析和投资建议
    4. 注意：美股价格单位为美元($)，港股价格单位为港币(HK$)，请在报告中明确标注
    """
    
    return call_deepseek_api(prompt)

def main():
    print(f"[{datetime.now()}] 启动多市场量化流水线...")
    
    # 统计待分析股票
    total_stocks = sum(len(symbols) for symbols in STOCK_CONFIG.values())
    if total_stocks == 0:
        print(f"[{datetime.now()}] ⚠️  警告: 股票配置为空，请在 STOCK_CONFIG 中添加股票代码")
        return
    
    for market, symbols in STOCK_CONFIG.items():
        if symbols:
            market_name = get_market_name(market)
            print(f"[{datetime.now()}] {market_name}待分析: {', '.join(symbols)}")
    
    try:
        # 1. 循环抓取与分析所有股票
        stocks_data = {}
        failed_stocks = []
        
        for market, symbols in STOCK_CONFIG.items():
            market_name = get_market_name(market)
            for symbol in symbols:
                try:
                    print(f"[{datetime.now()}] 正在分析{market_name} {symbol}...")
                    data = get_stock_analysis(symbol, market)
                    
                    if data is None:
                        print(f"[{datetime.now()}] ⚠️  {market_name} {symbol} 数据不足或分析失败，跳过")
                        failed_stocks.append(f"{market_name} {symbol}")
                        continue
                    
                    stocks_data[(market, symbol)] = data
                    rules_passed = count_rules_passed(data)
                    print(f"[{datetime.now()}] {market_name} {symbol} 分析完成，达成规则: {rules_passed}/10")
                except Exception as e:
                    error_msg = str(e)
                    print(f"[{datetime.now()}] ⚠️  {market_name} {symbol} 分析失败: {error_msg}")
                    failed_stocks.append(f"{market_name} {symbol}")
        
        if not stocks_data:
            print(f"[{datetime.now()}] ❌ 所有股票分析均失败，无法生成报告")
            return
        
        if failed_stocks:
            print(f"[{datetime.now()}] ⚠️  以下股票分析失败: {', '.join(failed_stocks)}")
        
        # 2. 调用 AI 决策生成综合报告
        print(f"[{datetime.now()}] 正在生成 AI 分析报告（共 {len(stocks_data)} 只股票）...")
        report_content = generate_ai_report(stocks_data)
        
        # 3. 提取标题并发送
        lines = report_content.split('\n')
        subject = f"AI 投研周报: {lines[0]}" if lines else f"多市场量化报告 ({len(stocks_data)} 只)"
        
        send_email(subject, report_content)
        print(f"[{datetime.now()}] ✅ 流水线执行成功，报告已推送至邮箱。")
        print(f"[{datetime.now()}] 成功分析股票数: {len(stocks_data)}/{total_stocks}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)

if __name__ == "__main__":
    main()
