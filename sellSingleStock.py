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

def find_last_death_cross_week(df):
    """
    找到最近一次MACD线DIF线向下穿过DEA线的那一周
    返回该周的索引和最低价，如果没有找到则返回None
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

def check_sell_signal(symbol="NVDA"):
    """
    检查是否应该卖出股票
    返回: (should_sell, analysis_data)
    """
    ticker = yf.Ticker(symbol)
    # 抓取 2 年周线数据确保有足够的历史数据
    df = ticker.history(period="2y", interval="1wk")
    
    if len(df) < 2:
        return False, {
            "error": "数据不足，无法进行分析",
            "price": None,
            "death_cross_week_low": None,
        }
    
    # 计算MACD
    df = calculate_macd(df)
    
    # 获取当前价格（实时价格或最新收盘价）
    try:
        # 尝试获取实时价格
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
            "reason": "未找到死亡交叉点"
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
        "reason": "当前价格已跌破死亡交叉周最低价" if should_sell else "当前价格未跌破死亡交叉周最低价"
    }

def generate_sell_report(stocks_data):
    """
    将多只股票的卖出分析结果喂给 DeepSeek，让它生成专业报告
    stocks_data: 字典，格式为 {symbol: data_dict, ...}
    """
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )
    
    # 构建所有股票的分析数据字符串
    stocks_analysis = []
    sell_stocks = []
    hold_stocks = []
    
    for symbol, data in stocks_data.items():
        if data.get('should_sell', False):
            sell_stocks.append(symbol)
        else:
            hold_stocks.append(symbol)
        
        stock_info = f"""
    ==========================================
    标的: {symbol}
    当前价格: ${data.get('price', 'N/A')}
    
    死亡交叉分析:
    - 是否找到死亡交叉: {"✅ 是" if data.get('death_cross_found', False) else "❌ 否"}
    - 死亡交叉周日期: {data.get('death_cross_date', 'N/A')}
    - 死亡交叉周最低价: ${data.get('death_cross_week_low', 'N/A')}
    - 价格跌幅: {data.get('price_drop_pct', 'N/A')}%
    
    卖出信号: {"🔴 建议卖出" if data.get('should_sell', False) else "🟢 继续持有"}
    原因: {data.get('reason', 'N/A')}
    ==========================================
        """
        stocks_analysis.append(stock_info)
    
    all_stocks_text = "\n".join(stocks_analysis)
    
    prompt = f"""
    你是资深价值投资分析师，擅长量化趋势分析。
    
    以下是需要分析的股票卖出信号列表（共 {len(stocks_data)} 只）：
    {all_stocks_text}
    
    请根据以上数据写一份专业的邮件报告。
    1. 标题为【卖出信号分析报告】
    2. 对每一只参与分析的个股分别进行如下操作：
       a. 首先列出当前关键值的数值，方便我去对比数据的正确性
       b. 说明是否找到死亡交叉点（MACD DIF向下穿过DEA）
       c. 如果找到死亡交叉点，说明死亡交叉周的最低价
       d. 说明当前价格是否跌破死亡交叉周的最低价
       e. 给出明确的卖出建议（卖出/继续持有）
    3. 最后给出所有股票的综合分析和操作建议
    4. 特别标注需要立即卖出的股票（如果有）
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
    print(f"[{datetime.now()}] 启动股票卖出信号检测流水线...")
    print(f"[{datetime.now()}] 待分析股票: {', '.join(STOCK_SYMBOLS)}")
    
    if not STOCK_SYMBOLS:
        print(f"[{datetime.now()}] ⚠️  警告: STOCK_SYMBOLS 列表为空，请在配置中添加股票代码")
        return
    
    try:
        # 1. 循环检查所有股票的卖出信号
        stocks_data = {}
        failed_stocks = []
        sell_signals = []
        
        for symbol in STOCK_SYMBOLS:
            try:
                print(f"[{datetime.now()}] 正在检查 {symbol} 的卖出信号...")
                should_sell, analysis_data = check_sell_signal(symbol)
                stocks_data[symbol] = analysis_data
                
                if should_sell:
                    sell_signals.append(symbol)
                    print(f"[{datetime.now()}] 🔴 {symbol} 触发卖出信号！")
                    print(f"[{datetime.now()}]    当前价格: ${analysis_data.get('price')}")
                    print(f"[{datetime.now()}]    死亡交叉周最低价: ${analysis_data.get('death_cross_week_low')}")
                else:
                    print(f"[{datetime.now()}] 🟢 {symbol} 继续持有")
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
        report_content = generate_sell_report(stocks_data)
        
        # 3. 提取标题并发送
        lines = report_content.split('\n')
        subject = f"卖出信号分析报告: {len(sell_signals)} 只股票建议卖出" if sell_signals else "卖出信号分析报告: 暂无卖出信号"
        
        send_email(subject, report_content)
        print(f"[{datetime.now()}] ✅ 流水线执行成功，报告已推送至邮箱。")
        print(f"[{datetime.now()}] 成功分析股票数: {len(stocks_data)}/{len(STOCK_SYMBOLS)}")
        if sell_signals:
            print(f"[{datetime.now()}] 🔴 建议卖出股票: {', '.join(sell_signals)}")
        
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

