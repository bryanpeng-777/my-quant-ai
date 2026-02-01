"""
ARK BIG IDEAS 2026 股票扫描脚本
扫描Cathie Wood ARK BIG IDEAS 2026报告中提到的股票，找出满足买入条件的股票
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

def get_ark_big_ideas_symbols():
    """
    获取ARK BIG IDEAS 2026报告中提到的股票代码列表
    基于Cathie Wood的ARK BIG IDEAS 2026报告
    """
    # ARK BIG IDEAS 2026 股票列表（按类别组织）
    ark_symbols = []
    
    # 1. AI (算力、软件等)
    ai_symbols = [
        "NVDA",   # 英伟达
        "AVGO",   # 博通
        "MSFT",   # 微软
        "AMD",    # 美国超微公司
        "TSM",    # 台积电
        "META",   # Meta Platforms
        "GOOG",   # 谷歌-C
        "AMZN",   # 亚马逊
        "AAPL",   # 苹果
    ]
    ark_symbols.extend(ai_symbols)
    
    # 2. 公有区块链与数字资产（排除加密货币，只包含股票）
    blockchain_symbols = [
        "COIN",   # Coinbase
        "CRCL",   # Circle
        "HOOD",   # Robinhood
    ]
    ark_symbols.extend(blockchain_symbols)
    
    # 3. 机器人技术
    # 3.1 人形机器人
    humanoid_robots = [
        "TSLA",   # 特斯拉
        "XPEV",   # 小鹏汽车
        # "UBTECH", # 优必选 (港股09880.HK，可能需要特殊处理)
    ]
    ark_symbols.extend(humanoid_robots)
    
    # 3.2 自动驾驶/机器人出租车
    autonomous_driving = [
        "TSLA",   # 特斯拉
        "BIDU",   # 百度
        "GOOGL",  # 谷歌 Waymo
        # "WRD",    # 文远知行 (可能不是公开交易股票)
        # "PONY",   # 小马智行 (可能不是公开交易股票)
        "AMZN",   # 亚马逊 Zoox
        "DIDIY",  # DiDi Global Inc
        # "NBIS",   # Nebius (可能不是公开交易股票)
        # "GRAB",   # Grab (可能不是公开交易股票)
    ]
    ark_symbols.extend(autonomous_driving)
    
    # 3.3 专用机器人
    specialized_robots = [
        "SYK",    # 史赛克
        "AMZN",   # 亚马逊
        "ISRG",   # 直觉外科公司
        "SYM",    # Symbotic
        "TER",    # 泰瑞达
    ]
    ark_symbols.extend(specialized_robots)
    
    # 4. 多组学&生物科技
    # 4.1 分子诊断
    molecular_diagnostics = [
        "ADPT",   # Adaptive Biotechnologies
        "GH",     # Guardant Health
        "NTRA",   # Natera
        "PSNL",   # Personalis
        "TEM",    # Tempus AI
        "VCYT",   # Veracyte
    ]
    ark_symbols.extend(molecular_diagnostics)
    
    # 4.2 多组学
    omics = [
        "ILMN",   # Illumina
        "PACB",   # Pacific Biosciences of California
        "TWST",   # Twist Bioscience
        "TXG",    # 10X Genomics
    ]
    ark_symbols.extend(omics)
    
    # 4.3 治疗
    therapeutics = [
        "BEAM",   # Beam Therapeutics
        "CRSP",   # CRISPR Therapeutics
        "NTLA",   # Intellia Therapeutics
        "PRME",   # Prime Medicine
    ]
    ark_symbols.extend(therapeutics)
    
    # 4.4 药物开发
    drug_development = [
        "ABSI",   # Absci Corp
        "RXRX",   # Recursion Pharmaceuticals
        "GBIO",   # Generation Bio
    ]
    ark_symbols.extend(drug_development)
    
    # 5. 能源与储能 - 未公布，暂不包含
    
    # 去重并保持顺序
    unique_symbols = list(dict.fromkeys(ark_symbols))
    
    return unique_symbols

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
    
    以下是ARK BIG IDEAS 2026股票扫描结果：
    - 总共发现 {total_worthy_count} 只股票满足买入条件（至少满足{MIN_RULES_PASSED}个检验项）
    - 以下仅展示满足规则数量最多的前5只股票的详细分析数据：
    
    {all_stocks_text}
    
    请根据以上数据写一份专业的邮件报告。
    1. 标题为【ARK BIG IDEAS 2026股票扫描报告 - {datetime.now().strftime('%Y-%m-%d')}】
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
    5. 特别说明：这些股票都是ARK BIG IDEAS 2026报告中提到的创新领域股票，涵盖AI、区块链、机器人、生物科技等前沿领域，请结合科技创新和成长投资理念进行分析
    """
    
    return call_deepseek_api(prompt)

def main():
    print(f"[{datetime.now()}] 启动ARK BIG IDEAS 2026股票扫描流水线...")
    
    try:
        # 1. 获取ARK BIG IDEAS 2026股票列表
        print(f"[{datetime.now()}] 正在获取ARK BIG IDEAS 2026股票列表...")
        ark_symbols = get_ark_big_ideas_symbols()
        print(f"[{datetime.now()}] 获取到 {len(ark_symbols)} 只股票")
        
        # 2. 循环分析所有股票
        failed_stocks = []
        worthy_stocks = []  # 值得买入的股票（满足至少MIN_RULES_PASSED个规则）
        
        for idx, symbol in enumerate(ark_symbols, 1):
            try:
                print(f"[{datetime.now()}] [{idx}/{len(ark_symbols)}] 正在分析 {symbol}...")
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
        print(f"[{datetime.now()}] 总计分析: {len(ark_symbols)} 只股票")
        print(f"[{datetime.now()}] 分析成功: {len(ark_symbols) - len(failed_stocks)} 只")
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
            subject = f"ARK BIG IDEAS 2026股票扫描报告 - {datetime.now().strftime('%Y-%m-%d')}"
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
ARK BIG IDEAS 2026股票扫描报告 - {datetime.now().strftime('%Y-%m-%d')}

扫描结果：
- 总计分析股票数: {len(ark_symbols)}
- 成功分析: {len(ark_symbols) - len(failed_stocks)} 只
- 分析失败: {len(failed_stocks)} 只
- 值得买入: 0 只（需要至少满足{MIN_RULES_PASSED}个规则）

本次扫描未发现满足买入条件的股票。建议继续观察市场变化。
            """
            send_email(f"ARK BIG IDEAS 2026股票扫描报告 - {datetime.now().strftime('%Y-%m-%d')}", summary)
            print(f"[{datetime.now()}] ✅ 扫描摘要已推送至邮箱。")
        
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)

if __name__ == "__main__":
    main()

