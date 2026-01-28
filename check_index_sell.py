"""
指数型股票卖出信号监控脚本
检查持仓指数股票是否触发卖出条件：
1. 当前月的10月线价格低于上一个月的10月线价格（月线趋势向下）
2. 10周线处于20周线之下（周线死叉）
满足任一条件即提示卖出，支持美股(US)和港股(HK)
"""
import json
from datetime import datetime
from pathlib import Path
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

# 持仓记录文件路径
INDEX_HOLDINGS_FILE = "index_holdings.json"


def load_index_holdings():
    """
    从 index_holdings.json 加载持仓记录
    
    Returns:
        持仓记录列表，如果文件不存在或为空则返回空列表
    """
    if not Path(INDEX_HOLDINGS_FILE).exists():
        return []
    
    try:
        with open(INDEX_HOLDINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('records', [])
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] ⚠️  警告: {INDEX_HOLDINGS_FILE} 文件格式错误")
        return []
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️  加载持仓记录时出错: {str(e)}")
        return []


def calculate_holding_days(purchase_date_str):
    """
    计算持有天数
    
    Args:
        purchase_date_str: 购买日期字符串，格式为 YYYY-MM-DD
    
    Returns:
        持有天数
    """
    try:
        purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d')
        return (datetime.now() - purchase_date).days
    except Exception:
        return None


def check_index_sell_signal(record):
    """
    检查单只指数型股票是否触发卖出信号
    
    卖出条件（满足任一即触发）：
    1. 当前月的10月线价格 < 上一个月的10月线价格（月线趋势向下）
    2. 10周线 < 20周线（周线死叉）
    
    Args:
        record: 持仓记录字典，包含 symbol, purchase_price, purchase_date, quantity(可选)
    
    Returns:
        (should_sell, analysis_data): 是否建议卖出和分析数据
    """
    symbol = record['symbol']
    purchase_price = record['purchase_price']
    purchase_date = record['purchase_date']
    quantity = record.get('quantity', None)
    
    # 自动识别市场类型
    market = detect_market(symbol)
    
    # 计算持有天数
    holding_days = calculate_holding_days(purchase_date)
    
    # 获取当前价格
    current_price = get_current_stock_price(symbol, market)
    
    if current_price is None:
        return None, {
            "error": "无法获取当前价格",
            "symbol": symbol,
            "market": market,
            "purchase_price": purchase_price,
            "purchase_date": purchase_date,
            "holding_days": holding_days,
            "quantity": quantity
        }
    
    # === 检查条件1：月线10MA趋势 ===
    monthly_df = get_stock_data(symbol, market, period="2y", interval="1mo")
    
    if monthly_df is None or len(monthly_df) < 12:
        return None, {
            "error": "无法获取足够的月线数据（需要至少12个月）",
            "symbol": symbol,
            "market": market,
            "purchase_price": purchase_price,
            "purchase_date": purchase_date,
            "holding_days": holding_days,
            "quantity": quantity,
            "current_price": current_price
        }
    
    # 计算月线10MA
    monthly_df['10MA'] = monthly_df['Close'].rolling(window=10).mean()
    
    current_10ma_monthly = monthly_df.iloc[-1]['10MA']
    prev_10ma_monthly = monthly_df.iloc[-2]['10MA']
    
    # 检查月线数据有效性
    import pandas as pd
    if pd.isna(current_10ma_monthly) or pd.isna(prev_10ma_monthly):
        return None, {
            "error": "月线10MA数据不足",
            "symbol": symbol,
            "market": market,
            "purchase_price": purchase_price,
            "purchase_date": purchase_date,
            "holding_days": holding_days,
            "quantity": quantity,
            "current_price": current_price
        }
    
    # 条件1：当前月10月线 < 上一月10月线（月线趋势向下）
    rule_1_triggered = current_10ma_monthly < prev_10ma_monthly
    
    # === 检查条件2：周线10MA vs 20MA ===
    weekly_df = get_stock_data(symbol, market, period="2y", interval="1wk")
    
    if weekly_df is None or len(weekly_df) < 25:
        return None, {
            "error": "无法获取足够的周线数据（需要至少25周）",
            "symbol": symbol,
            "market": market,
            "purchase_price": purchase_price,
            "purchase_date": purchase_date,
            "holding_days": holding_days,
            "quantity": quantity,
            "current_price": current_price,
            "current_10ma_monthly": round(current_10ma_monthly, 2),
            "prev_10ma_monthly": round(prev_10ma_monthly, 2),
            "rule_1_triggered": rule_1_triggered
        }
    
    # 计算周线均线
    weekly_df['10MA'] = weekly_df['Close'].rolling(window=10).mean()
    weekly_df['20MA'] = weekly_df['Close'].rolling(window=20).mean()
    
    ma10_weekly = weekly_df.iloc[-1]['10MA']
    ma20_weekly = weekly_df.iloc[-1]['20MA']
    
    # 检查周线数据有效性
    if pd.isna(ma10_weekly) or pd.isna(ma20_weekly):
        return None, {
            "error": "周线均线数据不足",
            "symbol": symbol,
            "market": market,
            "purchase_price": purchase_price,
            "purchase_date": purchase_date,
            "holding_days": holding_days,
            "quantity": quantity,
            "current_price": current_price,
            "current_10ma_monthly": round(current_10ma_monthly, 2),
            "prev_10ma_monthly": round(prev_10ma_monthly, 2),
            "rule_1_triggered": rule_1_triggered
        }
    
    # 条件2：10周线 < 20周线（周线死叉）
    rule_2_triggered = ma10_weekly < ma20_weekly
    
    # 任一条件触发即建议卖出
    should_sell = rule_1_triggered or rule_2_triggered
    
    # 计算盈亏
    change_pct = (current_price - purchase_price) / purchase_price * 100
    profit_amount = None
    if quantity is not None:
        profit_amount = (current_price - purchase_price) * quantity
    
    return should_sell, {
        "symbol": symbol,
        "market": market,
        "purchase_price": purchase_price,
        "purchase_date": purchase_date,
        "holding_days": holding_days,
        "quantity": quantity,
        "current_price": current_price,
        "change_pct": round(change_pct, 2),
        "profit_amount": round(profit_amount, 2) if profit_amount is not None else None,
        # 月线数据
        "current_10ma_monthly": round(current_10ma_monthly, 2),
        "prev_10ma_monthly": round(prev_10ma_monthly, 2),
        "rule_1_triggered": rule_1_triggered,  # 月线趋势向下
        # 周线数据
        "ma10_weekly": round(ma10_weekly, 2),
        "ma20_weekly": round(ma20_weekly, 2),
        "rule_2_triggered": rule_2_triggered,  # 周线死叉
        # 综合判断
        "should_sell": should_sell
    }


def check_all_index_holdings():
    """
    检查所有指数型股票持仓是否触发卖出信号
    
    Returns:
        (sell_records, all_records_data): 建议卖出的记录和所有记录的分析数据
    """
    records = load_index_holdings()
    
    if not records:
        print(f"[{datetime.now()}] 📋 暂无指数型股票持仓记录，无需检查")
        return [], {}
    
    print(f"[{datetime.now()}] 📋 开始检查 {len(records)} 条指数型股票持仓记录...")
    
    sell_records = []
    all_records_data = {}
    failed_records = []
    
    for record in records:
        symbol = record['symbol']
        market = detect_market(symbol)
        market_name = get_market_name(market)
        
        try:
            result, analysis_data = check_index_sell_signal(record)
            
            if result is None:
                # 获取数据失败
                error_msg = analysis_data.get('error', '未知错误')
                failed_records.append(f"{market_name} {symbol}: {error_msg}")
                all_records_data[(market, symbol)] = analysis_data
                print(f"[{datetime.now()}] ⚠️  {market_name} {symbol} 检查失败: {error_msg}")
                continue
            
            all_records_data[(market, symbol)] = analysis_data
            
            display_symbol = get_display_symbol(symbol, market)
            currency = get_currency_symbol(market)
            holding_days = analysis_data.get('holding_days', 'N/A')
            
            if result:
                # 触发卖出信号
                sell_records.append(analysis_data)
                print(f"[{datetime.now()}] 🔴 {market_name} {display_symbol} 触发卖出信号！")
                print(f"[{datetime.now()}]    买入日期: {analysis_data['purchase_date']} (已持有 {holding_days} 天)")
                print(f"[{datetime.now()}]    购买价格: {currency}{analysis_data['purchase_price']}")
                if analysis_data.get('quantity'):
                    print(f"[{datetime.now()}]    购买数量: {analysis_data['quantity']} 股")
                print(f"[{datetime.now()}]    当前价格: {currency}{analysis_data['current_price']}")
                
                # 显示触发的条件
                if analysis_data['rule_1_triggered']:
                    print(f"[{datetime.now()}]    ❌ 条件1触发: 月线10MA向下 ({currency}{analysis_data['current_10ma_monthly']} < {currency}{analysis_data['prev_10ma_monthly']})")
                if analysis_data['rule_2_triggered']:
                    print(f"[{datetime.now()}]    ❌ 条件2触发: 10周线 < 20周线 ({currency}{analysis_data['ma10_weekly']} < {currency}{analysis_data['ma20_weekly']})")
            else:
                # 继续持有
                change_pct = analysis_data.get('change_pct', 0)
                if change_pct >= 0:
                    change_info = f"涨幅: +{change_pct}%"
                else:
                    change_info = f"跌幅: {change_pct}%"
                print(f"[{datetime.now()}] 🟢 {market_name} {display_symbol} 继续持有 ({change_info}, 已持有 {holding_days} 天)")
        
        except Exception as e:
            error_msg = str(e)
            print(f"[{datetime.now()}] ⚠️  {market_name} {symbol} 检查失败: {error_msg}")
            failed_records.append(f"{market_name} {symbol}")
    
    if failed_records:
        print(f"[{datetime.now()}] ⚠️  以下股票检查失败:")
        for record in failed_records:
            print(f"[{datetime.now()}]    - {record}")
    
    return sell_records, all_records_data


def generate_index_sell_report(sell_records, all_records_data):
    """
    生成指数型股票卖出信号报告（使用AI生成）
    
    Args:
        sell_records: 建议卖出的记录列表
        all_records_data: 所有记录的分析数据字典
    
    Returns:
        AI 生成的报告内容
    """
    
    # 获取所有有效记录
    all_records_list = list(all_records_data.values())
    valid_records = [r for r in all_records_list if 'error' not in r]
    
    # 统计各市场股票数量
    us_count_all = sum(1 for r in valid_records if r['market'] == MARKET_US)
    hk_count_all = sum(1 for r in valid_records if r['market'] == MARKET_HK)
    
    us_count_sell = sum(1 for r in sell_records if r['market'] == MARKET_US)
    hk_count_sell = sum(1 for r in sell_records if r['market'] == MARKET_HK)
    
    # 构建分析文本
    stocks_analysis = []
    
    # 先列出建议卖出的记录
    if sell_records:
        stocks_analysis.append("═══════════════════════════════════════")
        stocks_analysis.append("建议卖出的持仓")
        stocks_analysis.append("═══════════════════════════════════════")
        
        for record in sell_records:
            market = record['market']
            symbol = record['symbol']
            market_name = get_market_name(market)
            currency = get_currency_symbol(market)
            display_symbol = get_display_symbol(symbol, market)
            
            quantity_info = ""
            if record.get('quantity'):
                quantity_info = f"购买数量: {record['quantity']} 股\n"
            
            change_pct = record.get('change_pct', 0)
            if change_pct >= 0:
                change_info = f"涨幅: +{change_pct}%"
            else:
                change_info = f"跌幅: {change_pct}%"
            
            profit_info = ""
            if record.get('profit_amount') is not None:
                profit_amount = record['profit_amount']
                if profit_amount >= 0:
                    profit_info = f"盈利金额: {currency}{profit_amount}\n"
                else:
                    profit_info = f"亏损金额: {currency}{profit_amount}\n"
            
            # 判断触发的条件
            trigger_reasons = []
            if record['rule_1_triggered']:
                trigger_reasons.append(f"月线10MA向下（当前: {currency}{record['current_10ma_monthly']} < 上月: {currency}{record['prev_10ma_monthly']}）")
            if record['rule_2_triggered']:
                trigger_reasons.append(f"10周线在20周线之下（{currency}{record['ma10_weekly']} < {currency}{record['ma20_weekly']}）")
            
            stock_info = f"""
==========================================
标的: {display_symbol} ({market_name})
买入日期: {record['purchase_date']}
已持有: {record.get('holding_days', 'N/A')} 天
购买价格: {currency}{record['purchase_price']}
{quantity_info}当前价格: {currency}{record['current_price']}
{change_info}
{profit_info}
月线分析:
- 当前月10月线: {currency}{record['current_10ma_monthly']}
- 上月10月线: {currency}{record['prev_10ma_monthly']}
- 月线趋势: {"🔴 向下" if record['rule_1_triggered'] else "🟢 向上"}

周线分析:
- 10周线: {currency}{record['ma10_weekly']}
- 20周线: {currency}{record['ma20_weekly']}
- 周线状态: {"🔴 10周线在20周线之下" if record['rule_2_triggered'] else "🟢 10周线在20周线之上"}

触发条件: {'; '.join(trigger_reasons)}
卖出信号: 🔴 建议卖出
==========================================
"""
            stocks_analysis.append(stock_info)
    
    # 列出继续持有的记录
    hold_records = [r for r in valid_records if not r.get('should_sell', False)]
    if hold_records:
        stocks_analysis.append("\n")
        stocks_analysis.append("═══════════════════════════════════════")
        stocks_analysis.append("继续持有的持仓")
        stocks_analysis.append("═══════════════════════════════════════")
        
        for record in hold_records:
            market = record['market']
            symbol = record['symbol']
            market_name = get_market_name(market)
            currency = get_currency_symbol(market)
            display_symbol = get_display_symbol(symbol, market)
            
            quantity_info = ""
            if record.get('quantity'):
                quantity_info = f"购买数量: {record['quantity']} 股\n"
            
            change_pct = record.get('change_pct', 0)
            if change_pct >= 0:
                change_info = f"涨幅: +{change_pct}%"
            else:
                change_info = f"跌幅: {change_pct}%"
            
            profit_info = ""
            if record.get('profit_amount') is not None:
                profit_amount = record['profit_amount']
                if profit_amount >= 0:
                    profit_info = f"盈利金额: {currency}{profit_amount}\n"
                else:
                    profit_info = f"亏损金额: {currency}{profit_amount}\n"
            
            stock_info = f"""
==========================================
标的: {display_symbol} ({market_name})
买入日期: {record['purchase_date']}
已持有: {record.get('holding_days', 'N/A')} 天
购买价格: {currency}{record['purchase_price']}
{quantity_info}当前价格: {currency}{record['current_price']}
{change_info}
{profit_info}
月线分析:
- 当前月10月线: {currency}{record['current_10ma_monthly']}
- 上月10月线: {currency}{record['prev_10ma_monthly']}
- 月线趋势: {"🔴 向下" if record['rule_1_triggered'] else "🟢 向上"}

周线分析:
- 10周线: {currency}{record['ma10_weekly']}
- 20周线: {currency}{record['ma20_weekly']}
- 周线状态: {"🔴 10周线在20周线之下" if record['rule_2_triggered'] else "🟢 10周线在20周线之上"}

卖出信号: 🟢 继续持有
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
    market_summary_all = "、".join(market_desc_all)
    
    market_desc_sell = []
    if us_count_sell > 0:
        market_desc_sell.append(f"美股 {us_count_sell} 只")
    if hk_count_sell > 0:
        market_desc_sell.append(f"港股 {hk_count_sell} 只")
    market_summary_sell = "、".join(market_desc_sell) if market_desc_sell else "无"
    
    # 统计
    total_records = len(valid_records)
    hold_count = len(hold_records)
    
    # 根据是否有卖出信号调整标题
    if sell_records:
        title = "【指数型股票卖出提醒】"
        trigger_section = f"本次监控发现 {len(sell_records)} 只指数型股票触发卖出信号（{market_summary_sell}），需要关注。"
    else:
        title = "【指数型股票监控报告】"
        trigger_section = "本次监控未发现触发卖出信号的指数型股票，所有持仓可继续持有。"
    
    prompt = f"""
    你是资深价值投资分析师，擅长指数投资和趋势分析，熟悉美股和港股市场的指数基金。
    
    {trigger_section}
    
    以下是本次监控的所有指数型股票持仓详情（共 {total_records} 只，包含 {market_summary_all}）：
    {all_stocks_text}
    
    卖出规则说明：
    1. 条件一：当前月的10月线价格 < 上一个月的10月线价格（月线趋势向下）
    2. 条件二：10周线 < 20周线（周线死叉）
    满足任一条件即建议卖出。这是一种趋势跟踪策略，适用于指数型股票的中长线投资。
    
    请根据以上数据写一份专业的邮件报告：
    1. 标题为{title}
    2. 对建议卖出的股票：
       a. 列出关键技术指标数值（10月线、10周线、20周线等）
       b. 说明买入日期、已持有天数、购买价格、当前价格
       c. 说明触发了哪个卖出条件
       d. 给出明确的卖出建议
    3. 对继续持有的股票：
       a. 简要说明当前状态
       b. 说明已持有天数和盈亏情况
       c. 说明技术指标状态（月线趋势、周线金叉/死叉状态）
    4. 最后给出综合分析和操作建议
    5. 注意：美股价格单位为美元($)，港股价格单位为港币(HK$)
    6. 本次监控共检查 {total_records} 只指数型股票，其中 {len(sell_records)} 只触发卖出信号，{hold_count} 只继续持有
    """
    
    return call_deepseek_api(prompt)


def main():
    print(f"[{datetime.now()}] 启动指数型股票卖出信号监控流水线...")
    
    try:
        # 1. 检查所有持仓
        sell_records, all_records_data = check_all_index_holdings()
        
        if not all_records_data:
            print(f"[{datetime.now()}] ❌ 没有可检查的持仓记录或所有记录检查均失败")
            return
        
        # 2. 生成报告并发送邮件
        valid_count = sum(1 for r in all_records_data.values() if 'error' not in r)
        print(f"[{datetime.now()}] 📊 本次检查了 {valid_count} 只指数型股票")
        if sell_records:
            print(f"[{datetime.now()}] 🔴 发现 {len(sell_records)} 只股票触发卖出信号")
        else:
            print(f"[{datetime.now()}] ✅ 所有持仓均未触发卖出条件，可继续持有")
        
        print(f"[{datetime.now()}] 正在生成 AI 分析报告...")
        report_content = generate_index_sell_report(sell_records, all_records_data)
        
        if report_content:
            # 3. 发送邮件通知
            if sell_records:
                subject = f"【指数型股票卖出提醒】{len(sell_records)}只股票触发卖出信号 - {datetime.now().strftime('%Y-%m-%d')}"
            else:
                subject = f"【指数型股票监控报告】今日无卖出信号 - {datetime.now().strftime('%Y-%m-%d')}"
            
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
