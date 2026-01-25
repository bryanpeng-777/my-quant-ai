"""
黄仁勋最新发言追踪脚本
搜索 NVIDIA CEO 黄仁勋（Jensen Huang）的最新公开发言、采访和演讲
"""
from datetime import datetime
import json
from duckduckgo_search import DDGS
from stock_utils import (
    call_deepseek_api,
    send_email,
    handle_pipeline_error
)

# ==========================================
# 搜索配置
# ==========================================
SEARCH_KEYWORDS = [
    "Jensen Huang interview",
    "Jensen Huang speech",
    "黄仁勋 发言",
    "黄仁勋 采访",
    "Jensen Huang NVIDIA keynote",
    "Jensen Huang latest comments",
]

MAX_RESULTS_PER_KEYWORD = 5  # 每个关键词搜索的最大结果数


def search_jensen_huang_news():
    """
    使用 DuckDuckGo 搜索黄仁勋的最新新闻和发言
    
    Returns:
        搜索结果列表，每个结果包含 title, body, href
    """
    all_results = []
    seen_urls = set()  # 用于去重
    
    with DDGS() as ddgs:
        for keyword in SEARCH_KEYWORDS:
            try:
                print(f"[{datetime.now()}] 搜索关键词: {keyword}")
                
                # 搜索新闻
                news_results = list(ddgs.news(
                    keyword,
                    region="wt-wt",  # 全球结果
                    safesearch="moderate",
                    timelimit="w",  # 限制为最近一周
                    max_results=MAX_RESULTS_PER_KEYWORD
                ))
                
                for result in news_results:
                    url = result.get('url', result.get('href', ''))
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append({
                            'title': result.get('title', ''),
                            'body': result.get('body', result.get('description', '')),
                            'url': url,
                            'date': result.get('date', ''),
                            'source': result.get('source', '')
                        })
                
                # 同时搜索普通网页
                text_results = list(ddgs.text(
                    keyword,
                    region="wt-wt",
                    safesearch="moderate",
                    timelimit="w",
                    max_results=MAX_RESULTS_PER_KEYWORD
                ))
                
                for result in text_results:
                    url = result.get('href', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append({
                            'title': result.get('title', ''),
                            'body': result.get('body', ''),
                            'url': url,
                            'date': '',
                            'source': ''
                        })
                        
            except Exception as e:
                print(f"[{datetime.now()}] ⚠️  搜索 '{keyword}' 时出错: {str(e)}")
                continue
    
    print(f"[{datetime.now()}] 共搜索到 {len(all_results)} 条结果（去重后）")
    return all_results


def generate_ai_report(search_results):
    """
    使用 DeepSeek 分析搜索结果，生成黄仁勋最新发言报告
    
    Args:
        search_results: 搜索结果列表
    
    Returns:
        AI 生成的报告内容
    """
    # 格式化搜索结果
    results_text = ""
    for idx, result in enumerate(search_results[:20], 1):  # 最多使用前20条结果
        results_text += f"""
---
{idx}. 标题: {result['title']}
来源: {result['source']}
日期: {result['date']}
摘要: {result['body']}
链接: {result['url']}
"""
    
    prompt = f"""
    你是一位专业的科技行业分析师，专门追踪 NVIDIA CEO 黄仁勋（Jensen Huang）的公开发言和观点。
    
    以下是最近搜索到的关于黄仁勋的新闻和信息：
    
    {results_text}
    
    请根据以上搜索结果，撰写一份专业的追踪报告，包含以下内容：
    
    1. 【报告标题】格式为：黄仁勋最新动态追踪报告 - {datetime.now().strftime('%Y-%m-%d')}
    
    2. 【最新发言摘要】
       - 整理黄仁勋最近的主要公开发言、采访或演讲
       - 提取他对 AI、GPU、NVIDIA 未来战略等话题的核心观点
       - 如果有具体的引用语句，请标注出来
    
    3. 【关键观点分析】
       - 黄仁勋对 AI 行业发展的看法
       - 对 NVIDIA 产品和技术路线的阐述
       - 对竞争对手或市场格局的评论
       - 对未来趋势的预测
    
    4. 【投资参考】
       - 这些发言对 NVIDIA 股价可能的影响
       - 投资者需要关注的要点
    
    5. 【原文链接】
       - 列出最相关的 3-5 个新闻链接，方便我进一步阅读原文
    
    注意：
    - 如果搜索结果中没有找到黄仁勋的直接发言，请如实说明
    - 保持客观，区分直接引用和推测
    - 报告语言为中文
    """
    
    return call_deepseek_api(prompt)


def main():
    print(f"[{datetime.now()}] 🚀 启动黄仁勋最新发言追踪流水线...")
    
    try:
        # 1. 搜索黄仁勋相关新闻
        print(f"[{datetime.now()}] 正在搜索黄仁勋最新新闻和发言...")
        search_results = search_jensen_huang_news()
        
        if not search_results:
            print(f"[{datetime.now()}] ⚠️  未搜索到任何相关新闻")
            # 发送一个简短的通知邮件
            summary = f"""
黄仁勋最新动态追踪报告 - {datetime.now().strftime('%Y-%m-%d')}

本次搜索未找到黄仁勋的最新公开发言或采访信息。

可能的原因：
1. 最近一周内没有重要的公开发言
2. 搜索结果被过滤
3. 网络搜索暂时不可用

建议：
- 可以手动访问 NVIDIA 官网查看最新新闻
- 关注 NVIDIA 的官方社交媒体账号
- 查看财经新闻网站的科技板块
            """
            send_email(
                f"黄仁勋最新动态追踪报告 - {datetime.now().strftime('%Y-%m-%d')}",
                summary
            )
            print(f"[{datetime.now()}] ✅ 通知邮件已发送")
            return
        
        # 2. 使用 AI 分析搜索结果
        print(f"[{datetime.now()}] 正在使用 AI 分析搜索结果...")
        report_content = generate_ai_report(search_results)
        
        # 3. 发送邮件
        subject = f"黄仁勋最新动态追踪报告 - {datetime.now().strftime('%Y-%m-%d')}"
        
        # 尝试从报告中提取标题
        lines = report_content.split('\n')
        for line in lines[:5]:
            if "【" in line and "】" in line and "黄仁勋" in line:
                title_match = line.split("【")[1].split("】")[0] if "】" in line else None
                if title_match:
                    subject = title_match
                    break
        
        send_email(subject, report_content)
        print(f"[{datetime.now()}] ✅ 流水线执行成功，报告已推送至邮箱。")
        
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)
        
        # 尝试发送错误通知
        try:
            error_report = f"""
黄仁勋最新动态追踪 - 执行异常通知

执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

错误信息:
{error_msg}

请检查流水线配置和网络连接。
            """
            send_email(
                f"⚠️ 黄仁勋追踪流水线异常 - {datetime.now().strftime('%Y-%m-%d')}",
                error_report
            )
        except Exception:
            print(f"[{datetime.now()}] ⚠️  无法发送错误通知邮件")


if __name__ == "__main__":
    main()

