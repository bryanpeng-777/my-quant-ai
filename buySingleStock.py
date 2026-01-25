"""
单股票买入分析脚本
分析指定股票是否满足买入条件，生成AI报告并发送邮件
"""
from datetime import datetime
from stock_utils import (
    get_config,
    get_stock_analysis,
    count_rules_passed,
    format_stock_analysis_text,
    call_deepseek_api,
    send_email,
    handle_pipeline_error
)

# ==========================================
# 股票代码配置：在此添加要分析的股票代码
# ==========================================
STOCK_SYMBOLS = [
    "NVDA",  # 英伟达
    "AAPL",  # 苹果
    "TSLA",  # 特斯拉
    "GOOGL",  # 谷歌
    "KO",  # 可口可乐
    "JD",  # 京东
    "BABA",  # 阿里
    "EDU",  # 新东方
    "BEKE",  # 贝壳
    "NTES",  # 网易
    "TSM",  # 台积电
    "NKE",  # 耐克
]

# 买入规则阈值
MIN_RULES_PASSED = 6

def generate_ai_report(stocks_data):
    """
    将多只股票的量化结果喂给 DeepSeek，让它生成专业投研结论
    
    Args:
        stocks_data: 字典，格式为 {symbol: data_dict, ...}
    
    Returns:
        AI 生成的报告内容
    """
    # 构建所有股票的分析数据字符串
    stocks_analysis = []
    for symbol, data in stocks_data.items():
        rules_passed = count_rules_passed(data)
        stock_info = format_stock_analysis_text(data, symbol)
        stock_info += f"综合结论: {'建议买入' if rules_passed >= MIN_RULES_PASSED else '持续观望'}\n"
        stocks_analysis.append(stock_info)
    
    all_stocks_text = "\n".join(stocks_analysis)
    
    prompt = f"""
    你是资深价值投资分析师，擅长量化趋势分析。
    
    以下是需要分析的股票列表（共 {len(stocks_data)} 只）：
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
    """
    
    return call_deepseek_api(prompt)

def main():
    print(f"[{datetime.now()}] 启动多股票量化流水线...")
    print(f"[{datetime.now()}] 待分析股票: {', '.join(STOCK_SYMBOLS)}")
    
    if not STOCK_SYMBOLS:
        print(f"[{datetime.now()}] ⚠️  警告: STOCK_SYMBOLS 列表为空，请在配置中添加股票代码")
        return
    
    try:
        # 1. 循环抓取与分析所有股票
        stocks_data = {}
        failed_stocks = []
        
        for symbol in STOCK_SYMBOLS:
            try:
                print(f"[{datetime.now()}] 正在分析 {symbol}...")
                data = get_stock_analysis(symbol)
                
                if data is None:
                    print(f"[{datetime.now()}] ⚠️  {symbol} 数据不足或分析失败，跳过")
                    failed_stocks.append(symbol)
                    continue
                
                stocks_data[symbol] = data
                rules_passed = count_rules_passed(data)
                print(f"[{datetime.now()}] {symbol} 分析完成，达成规则: {rules_passed}/10")
            except Exception as e:
                error_msg = str(e)
                print(f"[{datetime.now()}] ⚠️  {symbol} 分析失败: {error_msg}")
                failed_stocks.append(symbol)
        
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
        subject = f"AI 投研周报: {lines[0]}" if lines else f"多股票量化报告 ({len(stocks_data)} 只)"
        
        send_email(subject, report_content)
        print(f"[{datetime.now()}] ✅ 流水线执行成功，报告已推送至邮箱。")
        print(f"[{datetime.now()}] 成功分析股票数: {len(stocks_data)}/{len(STOCK_SYMBOLS)}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)

if __name__ == "__main__":
    main()
