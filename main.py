import os
import yfinance as yf
from openai import OpenAI
import smtplib
from email.message import EmailMessage
from datetime import datetime
import pandas as pd
import numpy as np

# ==========================================
# 核心配置：从 GitHub Secrets 读取环境变量
# ==========================================
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
SENDER_EMAIL = os.environ.get("EMAIL_SENDER")
SENDER_PASSWORD = os.environ.get("EMAIL_PASSWORD")
RECEIVER_EMAIL = os.environ.get("EMAIL_RECEIVER")

# ==========================================
# 股票代码配置：在此添加要分析的股票代码
# ==========================================
STOCK_SYMBOLS = [
    "NVDA",  # 英伟达
    # 在此添加更多股票代码，例如：
    "AAPL",  # 苹果
    # "MSFT",  # 微软
    "TSLA",  # 特斯拉
]

def calculate_macd(df, fast=12, slow=26, signal=9):
    """
    计算MACD指标
    """
    exp1 = df['Close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['Close'].ewm(span=slow, adjust=False).mean()
    df['MACD_DIF'] = exp1 - exp2
    df['MACD_DEA'] = df['MACD_DIF'].ewm(span=signal, adjust=False).mean()
    df['MACD'] = 2 * (df['MACD_DIF'] - df['MACD_DEA'])
    return df

def get_stock_analysis(symbol="NVDA"):
    """
    抓取美股数据，计算技术指标并返回完整的分析数据
    """
    ticker = yf.Ticker(symbol)
    # 抓取 2 年周线数据确保计算 30MA 时有足够样本
    df = ticker.history(period="2y", interval="1wk")
    
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
    rule_1 = ma10 > ma20
    
    # 检验项2: 当前股价是否处于20周线之上
    rule_2 = curr_price > ma20
    
    # 检验项3: 当前股价是否处于30周线之上
    rule_3 = curr_price > ma30
    
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
        # 找出下跌的周（收盘价低于开盘价或低于前一周收盘价）
        recent_6_weeks['IsDown'] = recent_6_weeks['Close'] < recent_6_weeks['Open']
        down_weeks = recent_6_weeks[recent_6_weeks['IsDown']]
        if len(down_weeks) >= 2:
            # 检查下跌周的成交量是否呈下降趋势
            volumes = down_weeks['Volume'].values
            if len(volumes) >= 2:
                # 计算成交量趋势（后一半的平均值小于前一半的平均值）
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
        rule_8 = curr_volume > prev_volume
    
    # 检验项9: MACD线是否DIF线在DEA线之上
    rule_9 = False
    if not pd.isna(latest['MACD_DIF']) and not pd.isna(latest['MACD_DEA']):
        rule_9 = latest['MACD_DIF'] > latest['MACD_DEA']
    
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
    }

def generate_ai_report(stocks_data):
    """
    将多只股票的量化结果喂给 DeepSeek，让它生成专业投研结论
    stocks_data: 字典，格式为 {symbol: data_dict, ...}
    """
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )
    
    # 构建所有股票的分析数据字符串
    stocks_analysis = []
    for symbol, data in stocks_data.items():
        # 计算达成规则的数量
        rules_passed = sum([
            data['rule_1'], data['rule_2'], data['rule_3'], data['rule_4'],
            data['rule_5'], data['rule_6'], data['rule_7'], data['rule_8'], data['rule_9']
        ])
        total_rules = 9
        
        stock_info = f"""
    ==========================================
    标的: {symbol}
    当前价格: ${data['price']}
    
    技术指标状况:
    - 周线 10MA: ${data['ma10']}
    - 周线 20MA: ${data['ma20']}
    - 周线 30MA: ${data['ma30']}
    - MACD DIF: {data['macd_dif']}
    - MACD DEA: {data['macd_dea']}
    - 上一周收盘价: ${data['prev_close']}
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
    
    达成情况: {rules_passed}/{total_rules} 项检验通过
    综合结论: {"建议买入" if rules_passed >= 6 else "持续观望"}
    ==========================================
        """
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
       b. 我希望检验的项包括：
          - 10周线是否位于20周线之上
          - 当前股价是否处于20周线之上
          - 当前股价是否处于30周线之上
          - 30周线目前的趋势是向上吗
          - 个股横盘是否超过6周（纵向波动小于20个点）
          - 横盘期间的下跌成交量是否有缩量的趋势
          - 当前这一周的收盘价是否比上一周的收盘价高出5%个点
          - 当前这一周的成交量是否比上一周高
          - MACD线是否DIF线在DEA线之上
       c. 针对上述所有项输出为一个清单，清单项为每一项校验是否通过，例如：
          10周线是否位于20周线之上：✅
          当前股价是否处于20周线之上：❌
    3. 最后给出所有股票的综合对比分析和投资建议
    """
    
    response = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content

def send_email(subject, body):
    """
    通过 SMTP 发送邮件（QQ邮箱）
    需要使用QQ邮箱的授权码，不是QQ密码
    """
    if not all([SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL]):
        raise ValueError("邮件配置不完整，请检查环境变量：EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER")
    
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL

    try:
        # QQ邮箱 SMTP 配置
        with smtplib.SMTP_SSL('smtp.qq.com', 465) as smtp:
            smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
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
                stocks_data[symbol] = data
                rules_passed = sum([
                    data['rule_1'], data['rule_2'], data['rule_3'], data['rule_4'],
                    data['rule_5'], data['rule_6'], data['rule_7'], data['rule_8'], data['rule_9']
                ])
                print(f"[{datetime.now()}] {symbol} 分析完成，达成规则: {rules_passed}/9")
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
        # 简单取 AI 返回的第一行作为标题
        lines = report_content.split('\n')
        subject = f"AI 投研周报: {lines[0]}" if lines else f"多股票量化报告 ({len(stocks_data)} 只)"
        
        send_email(subject, report_content)
        print(f"[{datetime.now()}] ✅ 流水线执行成功，报告已推送至邮箱。")
        print(f"[{datetime.now()}] 成功分析股票数: {len(stocks_data)}/{len(STOCK_SYMBOLS)}")
        
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        
        # 提供更友好的错误提示
        if "QQ邮箱认证失败" in error_msg or "535" in error_msg or "authentication failed" in error_msg.lower():
            print(f"[{datetime.now()}] ⚠️  邮件发送失败，但分析报告已生成。")
            print(f"[{datetime.now()}] 请按照上述提示配置 QQ邮箱授权码。")
        elif "API" in error_msg or "api_key" in error_msg.lower() or "DEEPSEEK" in error_msg:
            print(f"[{datetime.now()}] 提示: 请检查 DEEPSEEK_API_KEY 环境变量是否正确设置")
        elif "邮件配置不完整" in error_msg:
            print(f"[{datetime.now()}] 提示: 请检查邮箱相关环境变量（EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER）")

if __name__ == "__main__":
    main()