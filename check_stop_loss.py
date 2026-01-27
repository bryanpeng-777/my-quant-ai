"""
止损卖出监控脚本
检查持仓股票是否触发止损条件（价格跌破购买价7%）
支持美股(US)和港股(HK)，自动识别市场类型
"""
import json
from datetime import datetime
from pathlib import Path
from stock_utils import (
    MARKET_US,
    MARKET_HK,
    detect_market,
    get_current_stock_price,
    get_display_symbol,
    get_market_name,
    get_currency_symbol,
    call_deepseek_api,
    send_email,
    handle_pipeline_error
)

# 购买记录文件路径
PURCHASE_RECORDS_FILE = "purchase_records.json"

# 止损比例阈值
STOP_LOSS_THRESHOLD = 7.0  # 7%

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
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] ⚠️  警告: {PURCHASE_RECORDS_FILE} 文件格式错误")
        return []
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️  加载购买记录时出错: {str(e)}")
        return []

def check_stop_loss(record):
    """
    检查单条记录是否触发止损
    注意：同一只股票可能有多次买入，每次买入独立计算止损点
    
    Args:
        record: 购买记录字典，包含 symbol, purchase_price, purchase_date, quantity(可选)
    
    Returns:
        (triggered, analysis_data): 是否触发止损和分析数据
    """
    symbol = record['symbol']
    purchase_price = record['purchase_price']
    purchase_date = record['purchase_date']
    quantity = record.get('quantity', None)  # 购买数量（可选）
    
    # 自动识别市场类型
    market = detect_market(symbol)
    
    # 获取当前价格
    current_price = get_current_stock_price(symbol, market)
    
    if current_price is None:
        return None, {
            "error": "无法获取当前价格",
            "symbol": symbol,
            "market": market,
            "purchase_price": purchase_price,
            "purchase_date": purchase_date,
            "quantity": quantity
        }
    
    # 计算跌幅百分比（基于本次买入价格）
    drop_pct = (purchase_price - current_price) / purchase_price * 100
    
    # 判断是否触发止损（跌幅 >= 7%）
    # 注意：每次买入的止损点是独立的，基于各自的买入价格计算
    triggered = drop_pct >= STOP_LOSS_THRESHOLD
    
    # 计算盈亏金额（如果提供了数量）
    loss_amount = None
    if quantity is not None:
        loss_amount = (purchase_price - current_price) * quantity
    
    return triggered, {
        "symbol": symbol,
        "market": market,
        "purchase_price": purchase_price,
        "purchase_date": purchase_date,
        "quantity": quantity,
        "current_price": current_price,
        "drop_pct": round(drop_pct, 2),
        "loss_amount": round(loss_amount, 2) if loss_amount is not None else None,
        "triggered": triggered
    }

def check_all_stop_loss():
    """
    检查所有持仓是否触发止损
    
    Returns:
        (triggered_records, all_records_data): 触发止损的记录和所有记录的分析数据
    """
    records = load_purchase_records()
    
    if not records:
        print(f"[{datetime.now()}] 📋 暂无购买记录，无需检查")
        return [], {}
    
    print(f"[{datetime.now()}] 📋 开始检查 {len(records)} 条购买记录...")
    
    triggered_records = []
    all_records_data = {}
    failed_records = []
    
    for record in records:
        symbol = record['symbol']
        market = detect_market(symbol)
        market_name = get_market_name(market)
        
        try:
            result, analysis_data = check_stop_loss(record)
            
            if result is None:
                # 获取价格失败
                failed_records.append(f"{market_name} {symbol}")
                all_records_data[(market, symbol)] = analysis_data
                print(f"[{datetime.now()}] ⚠️  {market_name} {symbol} 无法获取当前价格")
                continue
            
            all_records_data[(market, symbol)] = analysis_data
            
            if result:
                # 触发止损
                triggered_records.append(analysis_data)
                display_symbol = get_display_symbol(symbol, market)
                currency = get_currency_symbol(market)
                print(f"[{datetime.now()}] 🔴 {market_name} {display_symbol} 触发止损信号！")
                print(f"[{datetime.now()}]    买入日期: {analysis_data['purchase_date']}")
                print(f"[{datetime.now()}]    购买价格: {currency}{analysis_data['purchase_price']}")
                if analysis_data.get('quantity'):
                    print(f"[{datetime.now()}]    购买数量: {analysis_data['quantity']} 股")
                print(f"[{datetime.now()}]    当前价格: {currency}{analysis_data['current_price']}")
                print(f"[{datetime.now()}]    跌幅: {analysis_data['drop_pct']}%")
                if analysis_data.get('loss_amount') is not None:
                    print(f"[{datetime.now()}]    亏损金额: {currency}{analysis_data['loss_amount']}")
            else:
                display_symbol = get_display_symbol(symbol, market)
                quantity_info = f" (数量: {analysis_data.get('quantity', 'N/A')}股)" if analysis_data.get('quantity') else ""
                print(f"[{datetime.now()}] 🟢 {market_name} {display_symbol} 未触发止损 (买入日期: {analysis_data['purchase_date']}, 跌幅: {analysis_data['drop_pct']}%{quantity_info})")
        
        except Exception as e:
            error_msg = str(e)
            print(f"[{datetime.now()}] ⚠️  {market_name} {symbol} 检查失败: {error_msg}")
            failed_records.append(f"{market_name} {symbol}")
    
    if failed_records:
        print(f"[{datetime.now()}] ⚠️  以下股票检查失败: {', '.join(failed_records)}")
    
    return triggered_records, all_records_data

def generate_stop_loss_report(triggered_records, all_records_data):
    """
    生成止损报告（使用AI生成）
    无论是否触发止损，都会生成包含所有记录的完整报告
    
    Args:
        triggered_records: 触发止损的记录列表
        all_records_data: 所有记录的分析数据字典
    
    Returns:
        AI 生成的报告内容
    """
    
    # 统计各市场股票数量（所有记录）
    all_records_list = list(all_records_data.values())
    # 过滤掉有错误的记录
    valid_records = [r for r in all_records_list if 'error' not in r]
    
    us_count_all = sum(1 for r in valid_records if r['market'] == MARKET_US)
    hk_count_all = sum(1 for r in valid_records if r['market'] == MARKET_HK)
    
    us_count_triggered = sum(1 for r in triggered_records if r['market'] == MARKET_US)
    hk_count_triggered = sum(1 for r in triggered_records if r['market'] == MARKET_HK)
    
    # 构建所有股票的分析数据字符串（包括触发和未触发的）
    stocks_analysis = []
    
    # 先列出触发止损的记录
    if triggered_records:
        stocks_analysis.append("═══════════════════════════════════════")
        stocks_analysis.append("触发止损的记录")
        stocks_analysis.append("═══════════════════════════════════════")
        
        for record in triggered_records:
            market = record['market']
            symbol = record['symbol']
            market_name = get_market_name(market)
            currency = get_currency_symbol(market)
            display_symbol = get_display_symbol(symbol, market)
            
            quantity_info = ""
            if record.get('quantity'):
                quantity_info = f"购买数量: {record['quantity']} 股\n"
            
            loss_amount_info = ""
            if record.get('loss_amount') is not None:
                loss_amount_info = f"亏损金额: {currency}{record['loss_amount']}\n"
            
            stock_info = f"""
==========================================
标的: {display_symbol} ({market_name})
买入日期: {record['purchase_date']}
购买价格: {currency}{record['purchase_price']}
{quantity_info}当前价格: {currency}{record['current_price']}
跌幅: {record['drop_pct']}%
{loss_amount_info}
止损信号: 🔴 触发止损（跌幅 >= {STOP_LOSS_THRESHOLD}%）
说明: 本次买入（{record['purchase_date']}）的止损点已触发，建议卖出本次买入的持仓
==========================================
"""
            stocks_analysis.append(stock_info)
    
    # 列出未触发止损的记录
    non_triggered_records = [r for r in valid_records if not r.get('triggered', False)]
    if non_triggered_records:
        stocks_analysis.append("\n")
        stocks_analysis.append("═══════════════════════════════════════")
        stocks_analysis.append("未触发止损的记录")
        stocks_analysis.append("═══════════════════════════════════════")
        
        for record in non_triggered_records:
            market = record['market']
            symbol = record['symbol']
            market_name = get_market_name(market)
            currency = get_currency_symbol(market)
            display_symbol = get_display_symbol(symbol, market)
            
            quantity_info = ""
            if record.get('quantity'):
                quantity_info = f"购买数量: {record['quantity']} 股\n"
            
            stock_info = f"""
==========================================
标的: {display_symbol} ({market_name})
买入日期: {record['purchase_date']}
购买价格: {currency}{record['purchase_price']}
{quantity_info}当前价格: {currency}{record['current_price']}
跌幅: {record['drop_pct']}%

止损信号: 🟢 未触发止损（跌幅 < {STOP_LOSS_THRESHOLD}%）
说明: 本次买入（{record['purchase_date']}）的止损点未触发，可继续持有
==========================================
"""
            stocks_analysis.append(stock_info)
    
    all_stocks_text = "\n".join(stocks_analysis)
    
    # 构建市场描述
    market_desc_all = []
    if us_count_all > 0:
        market_desc_all.append(f"美股 {us_count_all} 条")
    if hk_count_all > 0:
        market_desc_all.append(f"港股 {hk_count_all} 条")
    market_summary_all = "、".join(market_desc_all)
    
    market_desc_triggered = []
    if us_count_triggered > 0:
        market_desc_triggered.append(f"美股 {us_count_triggered} 条")
    if hk_count_triggered > 0:
        market_desc_triggered.append(f"港股 {hk_count_triggered} 条")
    market_summary_triggered = "、".join(market_desc_triggered) if market_desc_triggered else "无"
    
    # 统计未触发止损的记录
    total_records = len(valid_records)
    non_triggered_count = len(non_triggered_records)
    
    # 根据是否有触发止损，调整标题和提示词
    if triggered_records:
        title = "【止损卖出提醒】"
        trigger_section = f"本次监控发现 {len(triggered_records)} 条买入记录触发止损信号（包含 {market_summary_triggered}），需要立即关注。"
    else:
        title = "【止损监控报告】"
        trigger_section = "本次监控未发现触发止损的记录，所有持仓均正常。"
    
    prompt = f"""
    你是资深价值投资分析师，擅长量化趋势分析和风险控制，熟悉美股和港股市场。
    
    {trigger_section}
    
    以下是本次监控的所有买入记录详情（共 {total_records} 条，包含 {market_summary_all}）：
    {all_stocks_text}
    
    请根据以上数据写一份专业的邮件报告。
    1. 标题为{title}
    2. 重要说明：同一只股票可能有多次买入，每次买入的止损点是独立的，基于各自的买入价格计算。
       例如：如果某股票在150元买入100股，在145元买入50股，那么这两次买入的止损点分别是：
       - 第一次买入（150元）的止损点：150 × 0.93 = 139.5元
       - 第二次买入（145元）的止损点：145 × 0.93 = 134.85元
       如果当前价格是138元，那么第一次买入触发止损，第二次买入未触发。
    3. 对触发止损的记录：
       a. 首先列出当前关键值的数值，方便我去对比数据的正确性
       b. 说明买入日期、购买价格、购买数量（如有）、当前价格
       c. 说明跌幅百分比和亏损金额（如有）
       d. 明确说明本次买入已触发止损条件（跌幅 >= {STOP_LOSS_THRESHOLD}%）
       e. 给出明确的卖出建议（卖出本次买入的持仓数量）
    4. 对未触发止损的记录：
       a. 简要说明当前状态
       b. 说明距离止损点还有多少空间
    5. 最后给出所有持仓的综合分析和操作建议
    6. 如果有触发止损的记录，特别强调需要立即卖出的股票和对应的买入日期
    7. 注意：美股价格单位为美元($)，港股价格单位为港币(HK$)，请在报告中明确标注
    8. 本次监控共检查 {total_records} 条买入记录，其中 {len(triggered_records)} 条触发止损，{non_triggered_count} 条未触发
    """
    
    return call_deepseek_api(prompt)

def main():
    print(f"[{datetime.now()}] 启动止损卖出监控流水线...")
    
    try:
        # 1. 检查所有持仓
        triggered_records, all_records_data = check_all_stop_loss()
        
        if not all_records_data:
            print(f"[{datetime.now()}] ❌ 没有可检查的购买记录或所有记录检查均失败")
            return
        
        # 2. 无论是否触发止损，都生成报告并发送邮件
        print(f"[{datetime.now()}] 📊 本次检查了 {len(all_records_data)} 条买入记录")
        if triggered_records:
            print(f"[{datetime.now()}] 🔴 发现 {len(triggered_records)} 条记录触发止损信号")
        else:
            print(f"[{datetime.now()}] ✅ 所有持仓均未触发止损条件")
        
        print(f"[{datetime.now()}] 正在生成 AI 分析报告...")
        report_content = generate_stop_loss_report(triggered_records, all_records_data)
        
        if report_content:
            # 3. 发送邮件通知
            if triggered_records:
                subject = f"【止损卖出提醒】{len(triggered_records)}条记录触发止损信号 - {datetime.now().strftime('%Y-%m-%d')}"
            else:
                subject = f"【止损监控报告】今日无止损信号 - {datetime.now().strftime('%Y-%m-%d')}"
            
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
