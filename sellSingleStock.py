"""
股票卖出信号检测脚本
基于MACD死亡交叉分析，检测股票是否应该卖出
支持美股(US)和港股(HK)
"""
import json
import yfinance as yf
from datetime import datetime
from pathlib import Path
import pandas as pd
from stock_utils import (
    MARKET_US,
    MARKET_HK,
    calculate_macd,
    get_stock_data,
    normalize_symbol,
    get_display_symbol,
    get_market_name,
    get_currency_symbol,
    call_deepseek_api,
    send_email,
    handle_pipeline_error
)

# 购买记录文件路径
PURCHASE_RECORDS_FILE = "purchase_records.json"

# ==========================================
# 股票代码配置：在此添加要分析的股票代码
# 格式: {市场类型: [股票代码列表]}
# ==========================================
STOCK_CONFIG = {
    # 美股列表
    MARKET_US: [
        "GOOGL",  # 谷歌
        "ILMN",  # IIIumina
    ],
    # 港股列表
    MARKET_HK: [
        #"0700",   # 腾讯控股
    ],
}

def load_purchase_records():
    """
    从 purchase_records.json 加载购买记录
    
    Returns:
        购买记录列表，如果文件不存在或为空则返回空列表
    """
    if not Path(PURCHASE_RECORDS_FILE).exists():
        return []
    
    try:
        with open(PURCHASE_RECORDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('records', [])
    except (json.JSONDecodeError, Exception):
        return []

def get_purchase_info(symbol, market):
    """
    获取指定股票的购买信息（取最早买入日期，若记录均未配置 purchase_date 则返回 None, None）
    
    Args:
        symbol: 股票代码
        market: 市场类型
    
    Returns:
        (purchase_date, holding_days): 购买日期和持有天数，未找到返回 (None, None)
    """
    records = load_purchase_records()
    
    # 查找该股票的所有买入记录
    stock_records = []
    for record in records:
        record_symbol = record.get('symbol', '')
        # 处理港股代码前导零问题
        if market == MARKET_HK:
            # 统一去掉前导零进行比较
            normalized_record = record_symbol.lstrip('0')
            normalized_symbol = symbol.lstrip('0')
            if normalized_record == normalized_symbol:
                stock_records.append(record)
        else:
            if record_symbol.upper() == symbol.upper():
                stock_records.append(record)
    
    if not stock_records:
        return None, None
    
    # 取最早的买入日期
    earliest_record = min(stock_records, key=lambda x: x.get('purchase_date', '9999-12-31'))
    purchase_date = earliest_record.get('purchase_date')
    
    if not purchase_date:
        return None, None
    
    # 计算持有天数
    try:
        purchase_dt = datetime.strptime(purchase_date, "%Y-%m-%d")
        today = datetime.now()
        holding_days = (today - purchase_dt).days
        return purchase_date, holding_days
    except (ValueError, TypeError):
        return purchase_date, None

def find_last_death_cross_week(df):
    """
    找到最近一次MACD线DIF线向下穿过DEA线的那一周
    
    Args:
        df: 包含 MACD_DIF 和 MACD_DEA 列的 DataFrame
    
    Returns:
        (index, lowest_price): 死亡交叉周的索引和最低价，未找到返回 (None, None)
    """
    if len(df) < 2:
        return None, None
    
    # 从后往前查找死亡交叉（DIF向下穿过DEA）
    # 死亡交叉：前一周DIF > DEA，当前周DIF <= DEA
    for i in range(len(df) - 1, 0, -1):
        prev_dif = df.iloc[i-1]['MACD_DIF']
        prev_dea = df.iloc[i-1]['MACD_DEA']
        curr_dif = df.iloc[i]['MACD_DIF']
        curr_dea = df.iloc[i]['MACD_DEA']
        
        # 检查是否有有效值
        if pd.isna(prev_dif) or pd.isna(prev_dea) or pd.isna(curr_dif) or pd.isna(curr_dea):
            continue
        
        # 检查是否发生死亡交叉：前一周DIF在DEA之上，当前周DIF在DEA之下或相等
        if prev_dif > prev_dea and curr_dif <= curr_dea:
            # 找到死亡交叉，返回该周的最低价
            death_cross_week = df.iloc[i]
            lowest_price = death_cross_week['Low']
            return i, lowest_price
    
    return None, None

def check_sell_signal(symbol, market=MARKET_US):
    """
    检查是否应该卖出股票
    
    Args:
        symbol: 股票代码
        market: 市场类型 (US/HK)
    
    Returns:
        (should_sell, analysis_data): 是否应该卖出和分析数据
    """
    # 获取购买信息（持有天数）
    purchase_date, holding_days = get_purchase_info(symbol, market)
    
    df = get_stock_data(symbol, market)
    
    if df is None or len(df) < 2:
        return False, {
            "error": "数据不足，无法进行分析",
            "price": None,
            "death_cross_week_low": None,
            "market": market,
            "purchase_date": purchase_date,
            "holding_days": holding_days,
        }
    
    # 计算MACD
    df = calculate_macd(df)
    
    # 获取当前价格（实时价格或最新收盘价）
    try:
        # 尝试获取实时价格
        normalized_symbol = normalize_symbol(symbol, market)
        ticker = yf.Ticker(normalized_symbol)
        info = ticker.info
        current_price = info.get('regularMarketPrice') or info.get('currentPrice')
        if current_price is None:
            # 如果无法获取实时价格，使用最新一周的收盘价
            current_price = df.iloc[-1]['Close']
    except:
        # 如果获取实时价格失败，使用最新一周的收盘价
        current_price = df.iloc[-1]['Close']
    
    # 找到最近一次死亡交叉的那一周
    death_cross_index, death_cross_week_low = find_last_death_cross_week(df)
    
    if death_cross_index is None or death_cross_week_low is None:
        return False, {
            "price": round(current_price, 2),
            "death_cross_week_low": None,
            "death_cross_found": False,
            "should_sell": False,
            "reason": "未找到死亡交叉点",
            "market": market,
            "purchase_date": purchase_date,
            "holding_days": holding_days,
        }
    
    # 检查当前价格是否跌破死亡交叉周的最低价
    should_sell = current_price < death_cross_week_low
    
    # 获取死亡交叉周的日期
    death_cross_date = df.index[death_cross_index]
    
    return should_sell, {
        "price": round(current_price, 2),
        "death_cross_week_low": round(death_cross_week_low, 2),
        "death_cross_date": death_cross_date.strftime("%Y-%m-%d") if hasattr(death_cross_date, 'strftime') else str(death_cross_date),
        "death_cross_found": True,
        "should_sell": should_sell,
        "price_drop_pct": round(((current_price - death_cross_week_low) / death_cross_week_low * 100), 2) if death_cross_week_low > 0 else None,
        "reason": "当前价格已跌破死亡交叉周最低价" if should_sell else "当前价格未跌破死亡交叉周最低价",
        "market": market,
        "purchase_date": purchase_date,
        "holding_days": holding_days,
    }

def generate_sell_report(stocks_data):
    """
    将多只股票的卖出分析结果喂给 DeepSeek，让它生成专业报告
    
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
        market_name = get_market_name(market)
        currency = get_currency_symbol(market)
        display_symbol = get_display_symbol(symbol, market)
        
        # 持有天数信息
        holding_info = ""
        if data.get('purchase_date'):
            holding_info = f"买入日期: {data.get('purchase_date')}\n"
            if data.get('holding_days') is not None:
                holding_info += f"已持有天数: {data.get('holding_days')} 天\n"
        
        stock_info = f"""
==========================================
标的: {display_symbol} ({market_name})
{holding_info}当前价格: {currency}{data.get('price', 'N/A')}

死亡交叉分析:
- 是否找到死亡交叉: {"✅ 是" if data.get('death_cross_found', False) else "❌ 否"}
- 死亡交叉周日期: {data.get('death_cross_date', 'N/A')}
- 死亡交叉周最低价: {currency}{data.get('death_cross_week_low', 'N/A')}
- 价格跌幅: {data.get('price_drop_pct', 'N/A')}%

卖出信号: {"🔴 建议卖出" if data.get('should_sell', False) else "🟢 继续持有"}
原因: {data.get('reason', 'N/A')}
==========================================
"""
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
    
    以下是需要分析的股票卖出信号列表（共 {len(stocks_data)} 只，包含 {market_summary}）：
    {all_stocks_text}
    
    请根据以上数据写一份专业的邮件报告。
    1. 标题为【止盈卖出信号分析报告】
    2. 对每一只参与分析的个股分别进行如下操作：
       a. 首先列出当前关键值的数值，方便我去对比数据的正确性
       b. 说明是否找到死亡交叉点（MACD DIF向下穿过DEA）
       c. 如果找到死亡交叉点，说明死亡交叉周的最低价
       d. 说明当前价格是否跌破死亡交叉周的最低价
       e. 给出明确的卖出建议（卖出/继续持有）
    3. 最后给出所有股票的综合分析和操作建议
    4. 特别标注需要立即卖出的股票（如果有）
    5. 注意：美股价格单位为美元($)，港股价格单位为港币(HK$)，请在报告中明确标注
    """
    
    return call_deepseek_api(prompt)

def main():
    print(f"[{datetime.now()}] 启动多市场股票卖出信号检测流水线...")
    
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
        # 1. 循环检查所有股票的卖出信号
        stocks_data = {}
        failed_stocks = []
        sell_signals = []
        
        for market, symbols in STOCK_CONFIG.items():
            market_name = get_market_name(market)
            currency = get_currency_symbol(market)
            
            for symbol in symbols:
                try:
                    print(f"[{datetime.now()}] 正在检查{market_name} {symbol} 的卖出信号...")
                    should_sell, analysis_data = check_sell_signal(symbol, market)
                    stocks_data[(market, symbol)] = analysis_data
                    
                    if should_sell:
                        display_symbol = get_display_symbol(symbol, market)
                        sell_signals.append(f"{market_name} {display_symbol}")
                        print(f"[{datetime.now()}] 🔴 {market_name} {display_symbol} 触发卖出信号！")
                        if analysis_data.get('holding_days') is not None:
                            print(f"[{datetime.now()}]    已持有: {analysis_data.get('holding_days')} 天")
                        print(f"[{datetime.now()}]    当前价格: {currency}{analysis_data.get('price')}")
                        print(f"[{datetime.now()}]    死亡交叉周最低价: {currency}{analysis_data.get('death_cross_week_low')}")
                    else:
                        display_symbol = get_display_symbol(symbol, market)
                        holding_info = f" (已持有: {analysis_data.get('holding_days')}天)" if analysis_data.get('holding_days') is not None else ""
                        print(f"[{datetime.now()}] 🟢 {market_name} {display_symbol} 继续持有{holding_info}")
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
        report_content = generate_sell_report(stocks_data)
        
        # 3. 提取标题并发送
        subject = f"卖出信号分析报告: {len(sell_signals)} 只股票建议卖出" if sell_signals else "卖出信号分析报告: 暂无卖出信号"
        
        send_email(subject, report_content)
        print(f"[{datetime.now()}] ✅ 流水线执行成功，报告已推送至邮箱。")
        print(f"[{datetime.now()}] 成功分析股票数: {len(stocks_data)}/{total_stocks}")
        if sell_signals:
            print(f"[{datetime.now()}] 🔴 建议卖出股票: {', '.join(sell_signals)}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)

if __name__ == "__main__":
    main()
