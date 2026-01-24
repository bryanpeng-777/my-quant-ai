import os
import yfinance as yf
from google import genai
import smtplib
from email.message import EmailMessage
from datetime import datetime

# ==========================================
# 核心配置：从 GitHub Secrets 读取环境变量
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("EMAIL_SENDER")
SENDER_PASSWORD = os.environ.get("EMAIL_PASSWORD")
RECEIVER_EMAIL = os.environ.get("EMAIL_RECEIVER")

def get_stock_analysis(symbol="NVDA"):
    """
    抓取美股数据，计算 10/20/30 周均线并返回分析数据
    """
    ticker = yf.Ticker(symbol)
    # 抓取 2 年周线数据确保计算 30MA 时有足够样本
    df = ticker.history(period="2y", interval="1wk")
    
    # 计算周线均线
    df['10MA'] = df['Close'].rolling(window=10).mean()
    df['20MA'] = df['Close'].rolling(window=20).mean()
    df['30MA'] = df['Close'].rolling(window=30).mean()
    
    latest = df.iloc[-1]
    curr_price = latest['Close']
    ma10, ma20, ma30 = latest['10MA'], latest['20MA'], latest['30MA']
    
    # 逻辑判定
    rule_1 = ma10 > ma20
    rule_2 = curr_price > ma30
    
    return {
        "price": round(curr_price, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma30": round(ma30, 2),
        "rule_1": rule_1,
        "rule_2": rule_2
    }

def generate_ai_report(data, symbol="NVDA"):
    """
    将量化结果喂给 Gemini 3，让它生成专业投研结论
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    你是资深价值投资分析师，擅长量化趋势分析。
    标的: {symbol}
    当前价格: ${data['price']}
    
    技术指标状况:
    - 周线 10MA: ${data['ma10']}
    - 周线 20MA: ${data['ma20']}
    - 判定1 (10MA > 20MA): {"✅ 达成" if data['rule_1'] else "❌ 未达成"}
    
    - 周线 30MA: ${data['ma30']}
    - 判定2 (现价 > 30MA): {"✅ 达成" if data['rule_2'] else "❌ 未达成"}
    
    综合结论: {"建议买入" if (data['rule_1'] and data['rule_2']) else "持续观望"}
    
    请根据以上数据写一份专业的邮件报告。
    1. 标题必须包含【✅建议买入】或【❌持续观望】。
    2. 正文需简述技术面现状，解释为何符合或不符合规则。
    3. 最后给出一段温馨的风险提示。
    """
    
    response = client.models.generate_content(
        model="gemini-1.5-flash", # 2026年推荐使用的高性价比稳定版本
        contents=prompt
    )
    return response.text

def send_email(subject, body):
    """
    通过 SMTP 发送邮件
    """
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL

    # 这里以 Gmail 为例，如果是其他邮箱，请修改服务器地址
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp.send_message(msg)

def main():
    print(f"[{datetime.now()}] 启动 NVDA 量化流水线...")
    
    try:
        # 1. 抓取与分析
        data = get_stock_analysis("NVDA")
        
        # 2. 调用 AI 决策
        report_content = generate_ai_report(data)
        
        # 3. 提取标题并发送
        # 简单取 AI 返回的第一行作为标题
        lines = report_content.split('\n')
        subject = f"AI 投研周报: {lines[0]}" if lines else "NVDA 每日量化报告"
        
        send_email(subject, report_content)
        print(f"[{datetime.now()}] 流水线执行成功，报告已推送至邮箱。")
        
    except Exception as e:
        print(f"[{datetime.now()}] 流水线执行异常: {str(e)}")

if __name__ == "__main__":
    main()