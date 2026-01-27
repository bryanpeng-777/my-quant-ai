"""
股票分析工具库 - 公共函数模块
包含：配置读取、MACD计算、股票分析、邮件发送等公共功能
支持多市场：美股(US)、港股(HK)
"""
import os
import yfinance as yf
from openai import OpenAI
import smtplib
from email.message import EmailMessage
from datetime import datetime
import pandas as pd
import numpy as np

# ==========================================
# 支持的市场类型
# ==========================================
MARKET_US = "US"
MARKET_HK = "HK"

# ==========================================
# 核心配置：从 GitHub Secrets 读取环境变量
# ==========================================
def get_config():
    """获取环境变量配置"""
    return {
        "DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY"),
        "SENDER_EMAIL": os.environ.get("EMAIL_SENDER"),
        "SENDER_PASSWORD": os.environ.get("EMAIL_PASSWORD"),
        "RECEIVER_EMAIL": os.environ.get("EMAIL_RECEIVER"),
    }

# ==========================================
# 市场相关工具函数
# ==========================================
def get_currency_symbol(market):
    """
    获取市场对应的货币符号
    
    Args:
        market: 市场类型 (US/HK)
    
    Returns:
        货币符号字符串
    """
    return "HK$" if market == MARKET_HK else "$"

def get_market_name(market):
    """
    获取市场中文名称
    
    Args:
        market: 市场类型 (US/HK)
    
    Returns:
        市场中文名称
    """
    return "港股" if market == MARKET_HK else "美股"

def normalize_symbol(symbol, market):
    """
    标准化股票代码格式
    
    Args:
        symbol: 股票代码
        market: 市场类型 (US/HK)
    
    Returns:
        标准化后的代码（港股添加.HK后缀，美股保持原样）
    """
    symbol = symbol.strip().upper()
    
    if market == MARKET_HK:
        # 港股需要添加 .HK 后缀
        if symbol.endswith('.HK'):
            return symbol
        return f"{symbol}.HK"
    
    # 美股直接返回
    return symbol

def get_display_symbol(symbol, market):
    """
    获取用于显示的股票代码（移除后缀）
    
    Args:
        symbol: 股票代码
        market: 市场类型 (US/HK)
    
    Returns:
        显示用的代码
    """
    if market == MARKET_HK:
        return symbol.replace('.HK', '').replace('.hk', '')
    return symbol

def detect_market(symbol):
    """
    从股票代码自动识别市场类型
    
    规则：
    - 港股：4位纯数字（如：0700, 9988, 3690）
    - 美股：字母或字母+数字组合（如：AAPL, GOOGL, TSLA）
    
    Args:
        symbol: 股票代码
    
    Returns:
        市场类型 (US/HK)
    """
    symbol = symbol.strip()
    # 港股：4位纯数字
    if len(symbol) == 4 and symbol.isdigit():
        return MARKET_HK
    # 美股：其他情况
    return MARKET_US

# ==========================================
# MACD 计算
# ==========================================
def calculate_macd(df, fast=12, slow=26, signal=9):
    """
    计算MACD指标
    
    Args:
        df: 包含 'Close' 列的 DataFrame
        fast: 快线周期，默认12
        slow: 慢线周期，默认26
        signal: 信号线周期，默认9
    
    Returns:
        添加了 MACD_DIF, MACD_DEA, MACD 列的 DataFrame
    """
    exp1 = df['Close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['Close'].ewm(span=slow, adjust=False).mean()
    df['MACD_DIF'] = exp1 - exp2
    df['MACD_DEA'] = df['MACD_DIF'].ewm(span=signal, adjust=False).mean()
    df['MACD'] = 2 * (df['MACD_DIF'] - df['MACD_DEA'])
    return df

# ==========================================
# 股票数据获取
# ==========================================
def get_stock_data(symbol, market=MARKET_US, period="2y", interval="1wk"):
    """
    获取股票历史数据
    
    Args:
        symbol: 股票代码
        market: 市场类型 (US/HK)
        period: 数据周期，默认2年
        interval: 数据间隔，默认周线
    
    Returns:
        包含历史数据的 DataFrame，失败返回 None
    """
    try:
        normalized_symbol = normalize_symbol(symbol, market)
        ticker = yf.Ticker(normalized_symbol)
        df = ticker.history(period=period, interval=interval)
        return df if len(df) > 0 else None
    except Exception as e:
        market_name = get_market_name(market)
        print(f"获取{market_name} {symbol} 数据时出错: {str(e)}")
        return None

def get_current_stock_price(symbol, market):
    """
    获取股票当前价格
    
    Args:
        symbol: 股票代码
        market: 市场类型 (US/HK)
    
    Returns:
        当前价格，失败返回 None
    """
    try:
        normalized_symbol = normalize_symbol(symbol, market)
        ticker = yf.Ticker(normalized_symbol)
        info = ticker.info
        current_price = info.get('regularMarketPrice') or info.get('currentPrice')
        if current_price is None:
            # 尝试从历史数据获取最新收盘价
            df = get_stock_data(symbol, market, period="5d", interval="1d")
            if df is not None and len(df) > 0:
                current_price = df.iloc[-1]['Close']
        return round(current_price, 2) if current_price is not None else None
    except Exception as e:
        market_name = get_market_name(market)
        print(f"获取{market_name} {symbol} 当前价格时出错: {str(e)}")
        return None

# ==========================================
# 买入规则检验（10条规则）
# ==========================================
def check_buy_rules(df):
    """
    检验买入规则（10条规则）
    
    Args:
        df: 包含股票历史数据的 DataFrame（需要至少30周数据）
    
    Returns:
        包含所有规则检验结果和相关数据的字典，失败返回 None
    """
    if len(df) < 30:
        return None
    
    # 计算周线均线
    df['10MA'] = df['Close'].rolling(window=10).mean()
    df['20MA'] = df['Close'].rolling(window=20).mean()
    df['30MA'] = df['Close'].rolling(window=30).mean()
    
    # 计算MACD
    df = calculate_macd(df)
    
    # 获取最新数据
    latest = df.iloc[-1]
    prev_week = df.iloc[-2] if len(df) >= 2 else None
    
    curr_price = latest['Close']
    ma10, ma20, ma30 = latest['10MA'], latest['20MA'], latest['30MA']
    prev_ma30 = df.iloc[-2]['30MA'] if len(df) >= 2 and not pd.isna(df.iloc[-2]['30MA']) else None
    
    # 检验项1: 10周线是否位于20周线之上
    rule_1 = ma10 > ma20 if not pd.isna(ma10) and not pd.isna(ma20) else False
    
    # 检验项2: 当前股价是否处于20周线之上
    rule_2 = curr_price > ma20 if not pd.isna(ma20) else False
    
    # 检验项3: 当前股价是否处于30周线之上
    rule_3 = curr_price > ma30 if not pd.isna(ma30) else False
    
    # 检验项4: 30周线目前的趋势是向上吗（比较当前和前一周的30MA）
    rule_4 = False
    if prev_ma30 is not None and not pd.isna(ma30) and not pd.isna(prev_ma30):
        rule_4 = ma30 > prev_ma30
    
    # 检验项5: 个股横盘是否超过6周（纵向波动小于20个点）
    rule_5 = False
    if len(df) >= 6:
        recent_6_weeks = df.iloc[-6:]['Close']
        max_price = recent_6_weeks.max()
        min_price = recent_6_weeks.min()
        if max_price > 0:
            volatility_pct = ((max_price - min_price) / min_price) * 100
            rule_5 = volatility_pct < 20
    
    # 检验项6: 横盘期间的下跌成交量是否有缩量的趋势
    rule_6 = False
    if len(df) >= 6 and rule_5:
        recent_6_weeks = df.iloc[-6:].copy()
        recent_6_weeks['IsDown'] = recent_6_weeks['Close'] < recent_6_weeks['Open']
        down_weeks = recent_6_weeks[recent_6_weeks['IsDown']]
        if len(down_weeks) >= 2:
            volumes = down_weeks['Volume'].values
            if len(volumes) >= 2:
                mid = len(volumes) // 2
                early_avg = np.mean(volumes[:mid])
                late_avg = np.mean(volumes[mid:])
                if early_avg > 0:
                    rule_6 = late_avg < early_avg
    
    # 检验项7: 当前这一周的收盘价是否比上一周的收盘价高出5%个点
    rule_7 = False
    if prev_week is not None:
        prev_close = prev_week['Close']
        if prev_close > 0:
            price_change_pct = ((curr_price - prev_close) / prev_close) * 100
            rule_7 = price_change_pct >= 5
    
    # 检验项8: 当前这一周的成交量是否比上一周高
    rule_8 = False
    if prev_week is not None:
        curr_volume = latest['Volume']
        prev_volume = prev_week['Volume']
        if not pd.isna(curr_volume) and not pd.isna(prev_volume):
            rule_8 = curr_volume > prev_volume
    
    # 检验项9: MACD线是否DIF线在DEA线之上
    rule_9 = False
    if not pd.isna(latest['MACD_DIF']) and not pd.isna(latest['MACD_DEA']):
        rule_9 = latest['MACD_DIF'] > latest['MACD_DEA']
    
    # 检验项10: 最近一周的收盘价是否是至少10周的最高价
    rule_10 = False
    if len(df) >= 10:
        recent_10_weeks = df.iloc[-10:]['Close']
        max_price_10_weeks = recent_10_weeks.max()
        rule_10 = curr_price >= max_price_10_weeks
    
    return {
        "price": round(curr_price, 2),
        "ma10": round(ma10, 2) if not pd.isna(ma10) else None,
        "ma20": round(ma20, 2) if not pd.isna(ma20) else None,
        "ma30": round(ma30, 2) if not pd.isna(ma30) else None,
        "macd_dif": round(latest['MACD_DIF'], 4) if not pd.isna(latest['MACD_DIF']) else None,
        "macd_dea": round(latest['MACD_DEA'], 4) if not pd.isna(latest['MACD_DEA']) else None,
        "prev_close": round(prev_week['Close'], 2) if prev_week is not None else None,
        "curr_volume": round(latest['Volume'], 0) if not pd.isna(latest['Volume']) else None,
        "prev_volume": round(prev_week['Volume'], 0) if prev_week is not None and not pd.isna(prev_week['Volume']) else None,
        "rule_1": rule_1,  # 10周线是否位于20周线之上
        "rule_2": rule_2,  # 当前股价是否处于20周线之上
        "rule_3": rule_3,  # 当前股价是否处于30周线之上
        "rule_4": rule_4,  # 30周线目前的趋势是向上吗
        "rule_5": rule_5,  # 个股横盘是否超过6周（纵向波动小于20个点）
        "rule_6": rule_6,  # 横盘期间的下跌成交量是否有缩量的趋势
        "rule_7": rule_7,  # 当前这一周的收盘价是否比上一周的收盘价高出5%个点
        "rule_8": rule_8,  # 当前这一周的成交量是否比上一周高
        "rule_9": rule_9,  # MACD线是否DIF线在DEA线之上
        "rule_10": rule_10,  # 最近一周的收盘价是否是至少10周的最高价
    }

def get_stock_analysis(symbol, market=MARKET_US):
    """
    获取股票分析数据（包含买入规则检验）
    
    Args:
        symbol: 股票代码
        market: 市场类型 (US/HK)
    
    Returns:
        包含分析结果的字典，失败返回 None
    """
    try:
        df = get_stock_data(symbol, market)
        if df is None or len(df) < 30:
            return None
        
        result = check_buy_rules(df)
        if result:
            # 保存显示用的代码
            result["symbol"] = get_display_symbol(symbol, market)
            result["market"] = market
        return result
    except Exception as e:
        market_name = get_market_name(market)
        print(f"分析{market_name} {symbol} 时出错: {str(e)}")
        return None

def count_rules_passed(data):
    """
    计算达成规则的数量
    
    Args:
        data: 包含 rule_1 到 rule_10 的字典
    
    Returns:
        达成规则的数量
    """
    return sum([
        data['rule_1'], data['rule_2'], data['rule_3'], data['rule_4'],
        data['rule_5'], data['rule_6'], data['rule_7'], data['rule_8'], 
        data['rule_9'], data['rule_10']
    ])

# ==========================================
# 报告生成辅助函数
# ==========================================
def format_stock_analysis_text(data, symbol=None, market=None):
    """
    格式化单只股票的分析文本
    
    Args:
        data: 股票分析数据字典
        symbol: 股票代码（如果 data 中没有）
        market: 市场类型（如果 data 中没有）
    
    Returns:
        格式化的分析文本
    """
    stock_symbol = data.get('symbol', symbol)
    stock_market = data.get('market', market) or MARKET_US
    currency = get_currency_symbol(stock_market)
    market_name = get_market_name(stock_market)
    rules_passed = count_rules_passed(data)
    total_rules = 10
    
    return f"""
==========================================
标的: {stock_symbol} ({market_name})
当前价格: {currency}{data['price']}

技术指标状况:
- 周线 10MA: {currency}{data['ma10']}
- 周线 20MA: {currency}{data['ma20']}
- 周线 30MA: {currency}{data['ma30']}
- MACD DIF: {data['macd_dif']}
- MACD DEA: {data['macd_dea']}
- 上一周收盘价: {currency}{data['prev_close']}
- 当前周成交量: {data['curr_volume']}
- 上一周成交量: {data['prev_volume']}

检验项判定结果:
1. 10周线是否位于20周线之上: {"✅ 达成" if data['rule_1'] else "❌ 未达成"}
2. 当前股价是否处于20周线之上: {"✅ 达成" if data['rule_2'] else "❌ 未达成"}
3. 当前股价是否处于30周线之上: {"✅ 达成" if data['rule_3'] else "❌ 未达成"}
4. 30周线目前的趋势是向上吗: {"✅ 达成" if data['rule_4'] else "❌ 未达成"}
5. 个股横盘是否超过6周（纵向波动小于20个点）: {"✅ 达成" if data['rule_5'] else "❌ 未达成"}
6. 横盘期间的下跌成交量是否有缩量的趋势: {"✅ 达成" if data['rule_6'] else "❌ 未达成"}
7. 当前这一周的收盘价是否比上一周的收盘价高出5%个点: {"✅ 达成" if data['rule_7'] else "❌ 未达成"}
8. 当前这一周的成交量是否比上一周高: {"✅ 达成" if data['rule_8'] else "❌ 未达成"}
9. MACD线是否DIF线在DEA线之上: {"✅ 达成" if data['rule_9'] else "❌ 未达成"}
10. 最近一周的收盘价是否是至少10周的最高价: {"✅ 达成" if data['rule_10'] else "❌ 未达成"}

达成情况: {rules_passed}/{total_rules} 项检验通过
==========================================
"""

# ==========================================
# AI 报告生成
# ==========================================
def call_deepseek_api(prompt, api_key=None):
    """
    调用 DeepSeek API 生成报告
    
    Args:
        prompt: 提示词
        api_key: API密钥（可选，默认从环境变量获取）
    
    Returns:
        AI 生成的内容
    """
    if api_key is None:
        api_key = get_config()["DEEPSEEK_API_KEY"]
    
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com"
    )
    
    response = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content

# ==========================================
# 邮件发送
# ==========================================
def send_email(subject, body, config=None):
    """
    通过 SMTP 发送邮件（QQ邮箱）
    
    Args:
        subject: 邮件主题
        body: 邮件正文
        config: 配置字典（可选，默认从环境变量获取）
    """
    if config is None:
        config = get_config()
    
    sender_email = config["SENDER_EMAIL"]
    sender_password = config["SENDER_PASSWORD"]
    receiver_email = config["RECEIVER_EMAIL"]
    
    if not all([sender_email, sender_password, receiver_email]):
        raise ValueError("邮件配置不完整，请检查环境变量：EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER")
    
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver_email

    try:
        with smtplib.SMTP_SSL('smtp.qq.com', 465) as smtp:
            smtp.login(sender_email, sender_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        error_msg = str(e)
        if "535" in error_msg or "authentication failed" in error_msg.lower() or "认证失败" in error_msg:
            raise Exception(
                "QQ邮箱认证失败！\n"
                "解决方案：\n"
                "1. 登录QQ邮箱网页版：https://mail.qq.com\n"
                "2. 进入【设置】→【账户】\n"
                "3. 找到【POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务】\n"
                "4. 开启【POP3/SMTP服务】或【IMAP/SMTP服务】\n"
                "5. 点击【生成授权码】，按照提示发送短信验证\n"
                "6. 将生成的授权码（16位字符）设置为 EMAIL_PASSWORD\n"
                "⚠️  注意：必须使用授权码，不能使用QQ密码！\n"
                f"原始错误: {error_msg}"
            )
        else:
            raise Exception(f"SMTP 认证错误: {error_msg}")
    except Exception as e:
        raise Exception(f"发送邮件时出错: {str(e)}")

# ==========================================
# 错误处理辅助函数
# ==========================================
def handle_pipeline_error(error_msg):
    """
    处理流水线异常，提供友好的错误提示
    
    Args:
        error_msg: 错误信息
    """
    if "QQ邮箱认证失败" in error_msg or "535" in error_msg or "authentication failed" in error_msg.lower():
        print(f"[{datetime.now()}] ⚠️  邮件发送失败，但分析报告已生成。")
        print(f"[{datetime.now()}] 请按照上述提示配置 QQ邮箱授权码。")
    elif "API" in error_msg or "api_key" in error_msg.lower() or "DEEPSEEK" in error_msg:
        print(f"[{datetime.now()}] 提示: 请检查 DEEPSEEK_API_KEY 环境变量是否正确设置")
    elif "邮件配置不完整" in error_msg:
        print(f"[{datetime.now()}] 提示: 请检查邮箱相关环境变量（EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER）")
