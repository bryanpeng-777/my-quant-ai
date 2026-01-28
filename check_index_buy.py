"""
指数型股票买入信号监控脚本
检查指定指数型股票是否触发买入条件：
1. 当前月的10月线价格高于上一个月的10月线价格（月线趋势向上）
2. 10周线处于20周线之上（周线金叉）
同时满足两个条件才提示买入，支持美股(US)和港股(HK)
"""
import pandas as pd
from datetime import datetime
from stock_utils import (
    MARKET_US,
    MARKET_HK,
    detect_market,
    get_stock_data,
    get_current_stock_price,
    get_display_symbol,
    get_market_name,
    get_currency_symbol,
    call_deepseek_api,
    send_email,
    handle_pipeline_error
)

# ==========================================
# 配置：要监控的指数型股票列表
# ==========================================
INDEX_WATCHLIST = [
    "VOO",      # Vanguard S&P 500 ETF
    "2800",
    "BRK-B",    # 伯克希尔B类股票
]


def analyze_volume_trend(monthly_df):
    """
    分析最近10个月的量价关系
    
    规则：
    - 下跌时缩量（正向信号）
    - 上涨时放量（正向信号）
    - 对比上涨月和下跌月的总成交量
    
    Args:
        monthly_df: 月线数据 DataFrame
    
    Returns:
        量价分析结果字典
    """
    if len(monthly_df) < 10:
        return {"error": "数据不足10个月"}
    
    recent_10_months = monthly_df.iloc[-10:].copy()
    
    # 判断每月是上涨还是下跌
    recent_10_months['price_change'] = recent_10_months['Close'].diff()
    recent_10_months['is_up'] = recent_10_months['price_change'] > 0
    recent_10_months['volume_change'] = recent_10_months['Volume'].diff()
    
    # 分离上涨月和下跌月
    up_months = recent_10_months[recent_10_months['is_up'] == True]
    down_months = recent_10_months[recent_10_months['is_up'] == False]
    
    # 计算上涨月的总成交量
    total_up_volume = up_months['Volume'].sum() if len(up_months) > 0 else 0
    # 计算下跌月的总成交量
    total_down_volume = down_months['Volume'].sum() if len(down_months) > 0 else 0
    
    # 判断是否是正向信号：上涨总量 > 下跌总量
    positive_signal = total_up_volume > total_down_volume if total_up_volume > 0 and total_down_volume > 0 else False
    
    # 计算上涨月中放量的比例
    up_with_volume_increase = 0
    if len(up_months) > 0:
        up_with_volume_increase = len(up_months[up_months['volume_change'] > 0]) / len(up_months) * 100
    
    # 计算下跌月中缩量的比例
    down_with_volume_decrease = 0
    if len(down_months) > 0:
        down_with_volume_decrease = len(down_months[down_months['volume_change'] < 0]) / len(down_months) * 100
    
    # 计算量比（上涨总量/下跌总量）
    volume_ratio = total_up_volume / total_down_volume if total_down_volume > 0 else 0
    
    return {
        "up_months_count": len(up_months),
        "down_months_count": len(down_months),
        "total_up_volume": round(total_up_volume, 0),
        "total_down_volume": round(total_down_volume, 0),
        "volume_ratio": round(volume_ratio, 2),
        "up_with_volume_increase_pct": round(up_with_volume_increase, 1),
        "down_with_volume_decrease_pct": round(down_with_volume_decrease, 1),
        "positive_signal": positive_signal
    }


def check_index_buy_signal(symbol):
    """
    检查单只指数型股票是否触发买入信号
    
    买入条件（必须同时满足）：
    1. 当前月的10月线价格 > 上一个月的10月线价格（月线趋势向上）
    2. 10周线 > 20周线（周线金叉）
    
    Args:
        symbol: 股票代码
    
    Returns:
        (should_buy, analysis_data): 是否建议买入和分析数据
    """
    market = detect_market(symbol)
    
    # 获取当前价格
    current_price = get_current_stock_price(symbol, market)
    
    if current_price is None:
        return None, {
            "error": "无法获取当前价格",
            "symbol": symbol,
            "market": market
        }
    
    # === 检查条件1：月线10MA趋势 ===
    monthly_df = get_stock_data(symbol, market, period="2y", interval="1mo")
    
    if monthly_df is None or len(monthly_df) < 12:
        return None, {
            "error": "无法获取足够的月线数据（需要至少12个月）",
            "symbol": symbol,
            "market": market,
            "current_price": current_price
        }
    
    # 计算月线10MA
    monthly_df['10MA'] = monthly_df['Close'].rolling(window=10).mean()
    
    current_10ma_monthly = monthly_df.iloc[-1]['10MA']
    prev_10ma_monthly = monthly_df.iloc[-2]['10MA']
    
    if pd.isna(current_10ma_monthly) or pd.isna(prev_10ma_monthly):
        return None, {
            "error": "月线10MA数据不足",
            "symbol": symbol,
            "market": market,
            "current_price": current_price
        }
    
    # 条件1：当前月10月线 > 上一月10月线（月线趋势向上）
    rule_1_passed = current_10ma_monthly > prev_10ma_monthly
    
    # === 检查条件2：周线10MA vs 20MA ===
    weekly_df = get_stock_data(symbol, market, period="2y", interval="1wk")
    
    if weekly_df is None or len(weekly_df) < 25:
        return None, {
            "error": "无法获取足够的周线数据（需要至少25周）",
            "symbol": symbol,
            "market": market,
            "current_price": current_price,
            "current_10ma_monthly": round(current_10ma_monthly, 2),
            "prev_10ma_monthly": round(prev_10ma_monthly, 2),
            "rule_1_passed": rule_1_passed
        }
    
    # 计算周线均线
    weekly_df['10MA'] = weekly_df['Close'].rolling(window=10).mean()
    weekly_df['20MA'] = weekly_df['Close'].rolling(window=20).mean()
    
    ma10_weekly = weekly_df.iloc[-1]['10MA']
    ma20_weekly = weekly_df.iloc[-1]['20MA']
    
    if pd.isna(ma10_weekly) or pd.isna(ma20_weekly):
        return None, {
            "error": "周线均线数据不足",
            "symbol": symbol,
            "market": market,
            "current_price": current_price,
            "current_10ma_monthly": round(current_10ma_monthly, 2),
            "prev_10ma_monthly": round(prev_10ma_monthly, 2),
            "rule_1_passed": rule_1_passed
        }
    
    # 条件2：10周线 > 20周线（周线金叉）
    rule_2_passed = ma10_weekly > ma20_weekly
    
    # 两个条件同时满足才建议买入
    should_buy = rule_1_passed and rule_2_passed
    
    # === 量价分析：最近10个月的成交量变化 ===
    volume_analysis = analyze_volume_trend(monthly_df)
    
    return should_buy, {
        "symbol": symbol,
        "market": market,
        "current_price": current_price,
        # 月线数据
        "current_10ma_monthly": round(current_10ma_monthly, 2),
        "prev_10ma_monthly": round(prev_10ma_monthly, 2),
        "rule_1_passed": rule_1_passed,  # 月线趋势向上
        # 周线数据
        "ma10_weekly": round(ma10_weekly, 2),
        "ma20_weekly": round(ma20_weekly, 2),
        "rule_2_passed": rule_2_passed,  # 周线金叉
        # 综合判断
        "should_buy": should_buy,
        # 量价分析
        "volume_analysis": volume_analysis
    }


def check_all_watchlist():
    """
    检查所有监控列表中的指数型股票
    
    Returns:
        (buy_signals, all_records_data): 触发买入信号的记录和所有记录的分析数据
    """
    if not INDEX_WATCHLIST:
        print(f"[{datetime.now()}] 📋 监控列表为空，请在 INDEX_WATCHLIST 中配置要监控的股票")
        return [], {}
    
    print(f"[{datetime.now()}] 📋 开始检查 {len(INDEX_WATCHLIST)} 只指数型股票的买入信号...")
    
    buy_signals = []
    all_records_data = {}
    failed_records = []
    
    for symbol in INDEX_WATCHLIST:
        market = detect_market(symbol)
        market_name = get_market_name(market)
        
        try:
            result, analysis_data = check_index_buy_signal(symbol)
            
            if result is None:
                error_msg = analysis_data.get('error', '未知错误')
                failed_records.append(f"{market_name} {symbol}: {error_msg}")
                all_records_data[(market, symbol)] = analysis_data
                print(f"[{datetime.now()}] ⚠️  {market_name} {symbol} 检查失败: {error_msg}")
                continue
            
            all_records_data[(market, symbol)] = analysis_data
            
            display_symbol = get_display_symbol(symbol, market)
            currency = get_currency_symbol(market)
            
            if result:
                buy_signals.append(analysis_data)
                print(f"[{datetime.now()}] 🟢 {market_name} {display_symbol} 触发买入信号！")
                print(f"[{datetime.now()}]    当前价格: {currency}{analysis_data['current_price']}")
                print(f"[{datetime.now()}]    ✅ 条件1: 月线10MA向上 ({currency}{analysis_data['current_10ma_monthly']} > {currency}{analysis_data['prev_10ma_monthly']})")
                print(f"[{datetime.now()}]    ✅ 条件2: 10周线 > 20周线 ({currency}{analysis_data['ma10_weekly']} > {currency}{analysis_data['ma20_weekly']})")
                
                # 量价分析
                vol = analysis_data.get('volume_analysis', {})
                if vol.get('positive_signal'):
                    print(f"[{datetime.now()}]    ✅ 量价配合: 上涨放量下跌缩量 (量比: {vol.get('volume_ratio', 'N/A')})")
                else:
                    print(f"[{datetime.now()}]    ⚠️  量价配合一般 (量比: {vol.get('volume_ratio', 'N/A')})")
            else:
                # 输出未满足的条件
                status_parts = []
                if analysis_data['rule_1_passed']:
                    status_parts.append("月线✅")
                else:
                    status_parts.append("月线❌")
                if analysis_data['rule_2_passed']:
                    status_parts.append("周线✅")
                else:
                    status_parts.append("周线❌")
                    
                print(f"[{datetime.now()}] ⏳ {market_name} {display_symbol} 暂不符合买入条件 ({', '.join(status_parts)})")
        
        except Exception as e:
            error_msg = str(e)
            print(f"[{datetime.now()}] ⚠️  {market_name} {symbol} 检查失败: {error_msg}")
            failed_records.append(f"{market_name} {symbol}")
    
    if failed_records:
        print(f"[{datetime.now()}] ⚠️  以下股票检查失败:")
        for record in failed_records:
            print(f"[{datetime.now()}]    - {record}")
    
    return buy_signals, all_records_data


def generate_index_buy_report(buy_signals, all_records_data):
    """
    生成指数型股票买入信号报告（使用AI生成）
    
    Args:
        buy_signals: 触发买入信号的记录列表
        all_records_data: 所有记录的分析数据字典
    
    Returns:
        AI 生成的报告内容
    """
    all_records_list = list(all_records_data.values())
    valid_records = [r for r in all_records_list if 'error' not in r]
    
    # 统计各市场股票数量
    us_count_all = sum(1 for r in valid_records if r['market'] == MARKET_US)
    hk_count_all = sum(1 for r in valid_records if r['market'] == MARKET_HK)
    
    us_count_buy = sum(1 for r in buy_signals if r['market'] == MARKET_US)
    hk_count_buy = sum(1 for r in buy_signals if r['market'] == MARKET_HK)
    
    # 构建分析文本
    stocks_analysis = []
    
    # 先列出触发买入信号的记录
    if buy_signals:
        stocks_analysis.append("═══════════════════════════════════════")
        stocks_analysis.append("触发买入信号的标的")
        stocks_analysis.append("═══════════════════════════════════════")
        
        for record in buy_signals:
            market = record['market']
            symbol = record['symbol']
            market_name = get_market_name(market)
            currency = get_currency_symbol(market)
            display_symbol = get_display_symbol(symbol, market)
            vol = record.get('volume_analysis', {})
            
            stock_info = f"""
==========================================
标的: {display_symbol} ({market_name})
当前价格: {currency}{record['current_price']}

月线分析:
- 当前月10月线: {currency}{record['current_10ma_monthly']}
- 上月10月线: {currency}{record['prev_10ma_monthly']}
- 月线趋势: 🟢 向上

周线分析:
- 10周线: {currency}{record['ma10_weekly']}
- 20周线: {currency}{record['ma20_weekly']}
- 周线状态: 🟢 10周线在20周线之上（金叉）

量价分析（最近10个月）:
- 上涨月份数: {vol.get('up_months_count', 'N/A')}
- 下跌月份数: {vol.get('down_months_count', 'N/A')}
- 上涨月总成交量: {vol.get('total_up_volume', 'N/A')}
- 下跌月总成交量: {vol.get('total_down_volume', 'N/A')}
- 量比（上涨总量/下跌总量）: {vol.get('volume_ratio', 'N/A')}
- 上涨放量比例: {vol.get('up_with_volume_increase_pct', 'N/A')}%
- 下跌缩量比例: {vol.get('down_with_volume_decrease_pct', 'N/A')}%
- 量价配合: {"🟢 正向信号（上涨总量 > 下跌总量）" if vol.get('positive_signal') else "⚠️ 一般"}

买入信号: 🟢 建议买入（满足所有条件）
==========================================
"""
            stocks_analysis.append(stock_info)
    
    # 列出暂不符合条件的记录
    no_signal_records = [r for r in valid_records if not r.get('should_buy', False)]
    if no_signal_records:
        stocks_analysis.append("\n")
        stocks_analysis.append("═══════════════════════════════════════")
        stocks_analysis.append("暂不符合买入条件的标的")
        stocks_analysis.append("═══════════════════════════════════════")
        
        for record in no_signal_records:
            market = record['market']
            symbol = record['symbol']
            market_name = get_market_name(market)
            currency = get_currency_symbol(market)
            display_symbol = get_display_symbol(symbol, market)
            vol = record.get('volume_analysis', {})
            
            stock_info = f"""
==========================================
标的: {display_symbol} ({market_name})
当前价格: {currency}{record['current_price']}

月线分析:
- 当前月10月线: {currency}{record['current_10ma_monthly']}
- 上月10月线: {currency}{record['prev_10ma_monthly']}
- 月线趋势: {"🟢 向上" if record['rule_1_passed'] else "🔴 向下"}

周线分析:
- 10周线: {currency}{record['ma10_weekly']}
- 20周线: {currency}{record['ma20_weekly']}
- 周线状态: {"🟢 10周线在20周线之上" if record['rule_2_passed'] else "🔴 10周线在20周线之下"}

量价分析（最近10个月）:
- 量比（上涨/下跌）: {vol.get('volume_ratio', 'N/A')}
- 量价配合: {"🟢 正向信号" if vol.get('positive_signal') else "⚠️ 一般"}

买入信号: ⏳ 暂不建议买入（未满足全部条件）
==========================================
"""
            stocks_analysis.append(stock_info)
    
    all_stocks_text = "\n".join(stocks_analysis)
    
    # 构建市场描述
    market_desc_all = []
    if us_count_all > 0:
        market_desc_all.append(f"美股 {us_count_all} 只")
    if hk_count_all > 0:
        market_desc_all.append(f"港股 {hk_count_all} 只")
    market_summary_all = "、".join(market_desc_all) if market_desc_all else "无"
    
    market_desc_buy = []
    if us_count_buy > 0:
        market_desc_buy.append(f"美股 {us_count_buy} 只")
    if hk_count_buy > 0:
        market_desc_buy.append(f"港股 {hk_count_buy} 只")
    market_summary_buy = "、".join(market_desc_buy) if market_desc_buy else "无"
    
    # 统计
    total_records = len(valid_records)
    no_signal_count = len(no_signal_records)
    
    # 根据是否有买入信号调整标题
    if buy_signals:
        title = "【指数型股票买入提醒】"
        trigger_section = f"本次监控发现 {len(buy_signals)} 只指数型股票触发买入信号（{market_summary_buy}），可以考虑建仓。"
    else:
        title = "【指数型股票买入监控报告】"
        trigger_section = "本次监控未发现触发买入信号的指数型股票，建议继续观望。"
    
    prompt = f"""
    你是资深价值投资分析师，擅长指数投资和趋势分析，熟悉美股和港股市场的指数基金。
    
    {trigger_section}
    
    以下是本次监控的所有指数型股票详情（共 {total_records} 只，包含 {market_summary_all}）：
    {all_stocks_text}
    
    买入规则说明：
    1. 条件一：当前月的10月线价格 > 上一个月的10月线价格（月线趋势向上）
    2. 条件二：10周线 > 20周线（周线金叉）
    必须同时满足两个条件才建议买入。这是一种趋势跟踪策略，适用于指数型股票的中长线投资。
    
    量价分析规则：
    - 上涨放量、下跌缩量是正向信号，表明资金在积极介入
    - 量比 > 1 表示上涨月的总成交量大于下跌月的总成交量，是健康的量价关系
    - 我们对比的是最近10个月中，所有上涨月的总成交量 vs 所有下跌月的总成交量
    
    请根据以上数据写一份专业的邮件报告：
    1. 标题为{title}
    2. 对触发买入信号的股票：
       a. 首先列出当前关键值的数值，方便我去对比数据的正确性
       b. 列出关键技术指标数值（10月线、10周线、20周线等）
       c. 分析量价配合情况
       d. 给出明确的买入建议和建议仓位
    3. 对暂不符合条件的股票：
       a. 说明哪些条件未满足
       b. 说明需要观察的关键点
    4. 最后给出综合分析和操作建议
    5. 注意：美股价格单位为美元($)，港股价格单位为港币(HK$)
    6. 本次监控共检查 {total_records} 只指数型股票，其中 {len(buy_signals)} 只触发买入信号，{no_signal_count} 只暂不符合条件
    """
    
    return call_deepseek_api(prompt)


def main():
    print(f"[{datetime.now()}] 启动指数型股票买入信号监控流水线...")
    
    try:
        # 1. 检查所有监控列表
        buy_signals, all_records_data = check_all_watchlist()
        
        if not all_records_data:
            print(f"[{datetime.now()}] ❌ 没有可检查的股票或所有检查均失败")
            return
        
        # 2. 生成报告并发送邮件
        valid_count = sum(1 for r in all_records_data.values() if 'error' not in r)
        print(f"[{datetime.now()}] 📊 本次检查了 {valid_count} 只指数型股票")
        if buy_signals:
            print(f"[{datetime.now()}] 🟢 发现 {len(buy_signals)} 只股票触发买入信号")
        else:
            print(f"[{datetime.now()}] ⏳ 暂无触发买入信号的股票，继续观望")
        
        print(f"[{datetime.now()}] 正在生成 AI 分析报告...")
        report_content = generate_index_buy_report(buy_signals, all_records_data)
        
        if report_content:
            # 3. 发送邮件通知
            if buy_signals:
                subject = f"【指数型股票买入提醒】{len(buy_signals)}只股票触发买入信号 - {datetime.now().strftime('%Y-%m-%d')}"
            else:
                subject = f"【指数型股票买入监控】今日无买入信号 - {datetime.now().strftime('%Y-%m-%d')}"
            
            send_email(subject, report_content)
            print(f"[{datetime.now()}] ✅ 流水线执行成功，监控报告已推送至邮箱。")
        else:
            print(f"[{datetime.now()}] ⚠️  AI报告生成失败")
    
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)


if __name__ == "__main__":
    main()
